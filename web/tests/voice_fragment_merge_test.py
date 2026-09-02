"""碎片声纹自动合并单元测试（合成向量与临时目录，不加载模型、不碰真实声纹库）。"""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "bin"))

import voice_bank as vb  # noqa: E402
import voice_enroll as ve  # noqa: E402

DIM = 192


def vec(hot: int, seed: int = 0, noise: float = 0.01) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(0, noise, DIM).astype(np.float32)
    v[hot] += 1.0
    return v


def make_meeting(root: Path, voices: dict) -> Path:
    """voices: {voice_id: 轮次数} → 合成 transcript.spk.json。"""
    mdir = root / "meetings" / "synthetic"
    mdir.mkdir(parents=True)
    turns = []
    i = 0
    for vid, n in voices.items():
        for _ in range(n):
            turns.append({"start": float(i * 10), "end": float(i * 10 + 8),
                          "speaker": vid, "voice": vid, "text": "样例"})
            i += 1
    (mdir / "transcript.spk.json").write_text(
        json.dumps(turns, ensure_ascii=False), encoding="utf-8")
    return mdir


with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    bank_dir = root / "bank"
    (bank_dir / "emb").mkdir(parents=True)
    bank = {"schema": "speaker-bank/v3", "voices": [], "persons": []}
    big = vb.add_voice(bank_dir, bank, vec(0, 1), "说话人1", "synthetic")
    # 碎片 A：与大声纹几乎同向(0.80 应命中)
    frag_a = vb.add_voice(bank_dir, bank, vec(0, 2), "说话人1(声音2)", "synthetic")
    # 碎片 B：正交方向(不应命中)
    frag_b = vb.add_voice(bank_dir, bank, vec(5, 3), "说话人3", "synthetic")
    # 碎片 C：已人工绑定(不应被动)
    person = vb.add_person(bank, "人员甲")
    frag_c = vb.add_voice(bank_dir, bank, vec(0, 4), "说话人1(声音3)", "synthetic",
                          person_id=person["id"])
    vb.save_bank(bank_dir, bank)
    mdir = make_meeting(root, {big["id"]: 10, frag_a["id"]: 1,
                               frag_b["id"]: 1, frag_c["id"]: 1})

    out = ve.merge_fragment_voices(mdir, bank_dir=bank_dir)
    assert out == {"merged": 1, "turns": 1}, out

    turns = json.loads((mdir / "transcript.spk.json").read_text(encoding="utf-8"))
    assert sum(1 for t in turns if t["voice"] == big["id"]) == 11
    assert sum(1 for t in turns if t["voice"] == frag_b["id"]) == 1
    assert sum(1 for t in turns if t["voice"] == frag_c["id"]) == 1

    bank2 = vb.load_bank(bank_dir)
    ids = [v["id"] for v in bank2["voices"]]
    assert frag_a["id"] not in ids, "单来源碎片应删条目"
    assert frag_b["id"] in ids and frag_c["id"] in ids
    assert not (bank_dir / frag_a["emb"]).exists(), "碎片向量文件应删除"

    # 幂等：再跑一次无变化
    assert ve.merge_fragment_voices(mdir, bank_dir=bank_dir) == {"merged": 0, "turns": 0}

with tempfile.TemporaryDirectory() as td:
    # 两个高度相似的 pyannote 聚类仍必须保留两个匿名 voice；本场刚创建的
    # voice 不能在同一 enrollment 循环中吞并后续聚类。再次运行应按
    # source_clusters 幂等复用，而不是继续增殖 voice。
    bank_dir = Path(td) / "bank"
    first = {"说话人1": vec(10, 20), "说话人2": vec(10, 21)}
    _, voice_of, linked, new = ve.enroll(first, "session-a", bank_dir=bank_dir)
    assert new == 2 and linked == 0
    assert voice_of["说话人1"] != voice_of["说话人2"]
    saved = vb.load_bank(bank_dir)
    assert len(saved["voices"]) == 2
    assert all(v.get("source_clusters", {}).get("session-a") for v in saved["voices"])

    _, again, linked2, new2 = ve.enroll(first, "session-a", bank_dir=bank_dir)
    assert again == voice_of
    assert linked2 == 2 and new2 == 0
    assert len(vb.load_bank(bank_dir)["voices"]) == 2

with tempfile.TemporaryDirectory() as td:
    # 旧版本曾把两个本场聚类压进同一匿名 voice。受控重跑应复用其中一个、
    # 为另一个建立独立 voice，并把精确映射迁移到唯一归属。
    bank_dir = Path(td) / "bank"
    bank = {"schema": "speaker-bank/v3", "voices": [], "persons": []}
    collapsed = vb.add_voice(bank_dir, bank, vec(12, 30), "说话人6", "session-b")
    collapsed["source_clusters"] = {"session-b": ["说话人6", "说话人8"]}
    vb.save_bank(bank_dir, bank)
    labels = {"说话人6": vec(12, 31), "说话人8": vec(12, 32)}
    _, split_map, _, split_new = ve.enroll(labels, "session-b", bank_dir=bank_dir)
    assert split_new == 1
    assert split_map["说话人6"] == collapsed["id"]
    assert split_map["说话人8"] != collapsed["id"]
    saved = vb.load_bank(bank_dir)
    owners = {
        label: [v["id"] for v in saved["voices"]
                if label in v.get("source_clusters", {}).get("session-b", [])]
        for label in labels
    }
    assert all(len(ids) == 1 for ids in owners.values()), owners

with tempfile.TemporaryDirectory() as td:
    # 已由用户确认归属同一人的 voice 仍可吸收同场多个强相似声学聚类，保留
    # 跨设备/音色轻微变化下的一人多簇能力。
    bank_dir = Path(td) / "bank"
    bank = {"schema": "speaker-bank/v3", "voices": [], "persons": []}
    person = vb.add_person(bank, "Synthetic Person")
    known = vb.add_voice(bank_dir, bank, vec(14, 40), "Synthetic Person", "older-session",
                         person_id=person["id"])
    vb.save_bank(bank_dir, bank)
    labels = {"说话人1": vec(14, 41), "说话人2": vec(14, 42)}
    _, known_map, known_linked, known_new = ve.enroll(
        labels, "session-c", bank_dir=bank_dir)
    assert known_new == 0 and known_linked == 2
    assert set(known_map.values()) == {known["id"]}

with tempfile.TemporaryDirectory() as td:
    # 嘈杂会议中，第二个聚类即使越过普通 0.70 门槛，也不能弱命中已经在本场
    # 出现的已确认人物；它应保留为独立匿名 voice，等待用户确认。
    bank_dir = Path(td) / "bank"
    bank = {"schema": "speaker-bank/v3", "voices": [], "persons": []}
    person = vb.add_person(bank, "Synthetic Person")
    target = np.zeros(DIM, dtype=np.float32)
    target[0] = 1.0
    known = vb.add_voice(bank_dir, bank, target, "Synthetic Person", "older-session",
                         person_id=person["id"])
    vb.save_bank(bank_dir, bank)
    weak = np.zeros(DIM, dtype=np.float32)
    weak[0] = 0.76
    weak[1] = np.sqrt(1.0 - weak[0] ** 2)
    labels = {"说话人1": target.copy(), "说话人2": weak}
    rename, guarded, guarded_linked, guarded_new = ve.enroll(
        labels, "session-d", bank_dir=bank_dir)
    assert guarded_linked == 1 and guarded_new == 1
    assert guarded["说话人1"] == known["id"]
    assert guarded["说话人2"] != known["id"]
    assert rename["说话人2"].startswith("说话人")

with tempfile.TemporaryDirectory() as td:
    # 旧版本已经把两个本场聚类保存到同一个已绑定 voice 时，受控重跑也必须
    # 重新检查第二簇的真实相似度，并迁移弱映射，而不是被精确 source 映射锁死。
    bank_dir = Path(td) / "bank"
    bank = {"schema": "speaker-bank/v3", "voices": [], "persons": []}
    person = vb.add_person(bank, "Synthetic Person")
    target = np.zeros(DIM, dtype=np.float32)
    target[0] = 1.0
    known = vb.add_voice(bank_dir, bank, target, "Synthetic Person", "older-session",
                         person_id=person["id"])
    known["source_clusters"] = {"session-e": ["说话人1", "说话人2"]}
    vb.save_bank(bank_dir, bank)
    weak = np.zeros(DIM, dtype=np.float32)
    weak[0] = 0.76
    weak[1] = np.sqrt(1.0 - weak[0] ** 2)
    labels = {"说话人1": target.copy(), "说话人2": weak}
    _, healed, _, healed_new = ve.enroll(labels, "session-e", bank_dir=bank_dir)
    assert healed_new == 1
    assert healed["说话人1"] == known["id"]
    assert healed["说话人2"] != known["id"]
    saved = vb.load_bank(bank_dir)
    old = next(voice for voice in saved["voices"] if voice["id"] == known["id"])
    assert old.get("source_clusters", {}).get("session-e") == ["说话人1"]

print("voice enrollment isolation and fragment merge: synthetic bank passed")
