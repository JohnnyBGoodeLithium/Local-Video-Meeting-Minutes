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

print("voice fragment merge: synthetic bank passed")
