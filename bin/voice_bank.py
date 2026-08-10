"""声纹库读写/比对共享模块（teams_minutes.py 与 voice_tool.py 共用）。

库结构 v2（speaker_bank/）：
    bank.json   {"persons": [{id,name,aliases,created}], "voices": [{id,person_id,label_hint,emb,sources,created}]}
    emb/v_XXXX.npy   每条声纹的质心向量(L2 归一化)
    orgchart.json    用户自放的 BU 架构(可选)，只被本地脚本读取——云端 agent 不读。

设计：人(person) 与 声纹(voice) 分离。一个人可挂多条声纹(聚类过拆/音色变化)，
匹配在声纹层做(取最大相似度)，显示名取 person.name，未绑定显示 label_hint。
"""

import difflib
import json
import time
from pathlib import Path

import numpy as np

SCHEMA = 2


def load_bank(bank_dir: Path) -> dict:
    path = Path(bank_dir) / "bank.json"
    if not path.is_file():
        return {"schema": SCHEMA, "persons": [], "voices": []}
    bank = json.loads(path.read_text(encoding="utf-8"))
    if bank.get("schema") != SCHEMA:  # v1: voices 带 name 字段, 无 persons
        persons, voices = [], []
        for v in bank.get("voices", []):
            name = v.get("name") or ""
            pid = None
            if name and "(声音" not in name and name != "未知":
                pid = f"p_{len(persons)+1:04d}"
                persons.append({"id": pid, "name": name, "aliases": [],
                                "created": v.get("created", "")})
            voices.append({"id": v["id"], "person_id": pid, "label_hint": name,
                           "emb": v["emb"], "sources": v.get("sources", []),
                           "created": v.get("created", "")})
        bank = {"schema": SCHEMA, "persons": persons, "voices": voices}
        save_bank(Path(bank_dir), bank)
    return bank


def save_bank(bank_dir: Path, bank: dict):
    Path(bank_dir).mkdir(parents=True, exist_ok=True)
    (Path(bank_dir) / "emb").mkdir(exist_ok=True)
    (Path(bank_dir) / "bank.json").write_text(
        json.dumps(bank, ensure_ascii=False, indent=1), encoding="utf-8")


def vec_of(bank_dir: Path, voice: dict) -> np.ndarray:
    v = np.load(Path(bank_dir) / voice["emb"]).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def person_name(bank: dict, person_id):
    for p in bank["persons"]:
        if p["id"] == person_id:
            return p["name"]
    return None


def display_name(bank: dict, voice: dict) -> str:
    return person_name(bank, voice.get("person_id")) or voice.get("label_hint") or voice["id"]


def match_voice(bank_dir: Path, bank: dict, vec, threshold: float):
    """返回 (best_voice, sim)；无库或无超过阈值 → (None, sim)。"""
    v = np.asarray(vec, dtype=np.float32)
    v = v / (np.linalg.norm(v) + 1e-9)
    best, best_sim = None, -1.0
    for entry in bank["voices"]:
        sim = float(np.dot(v, vec_of(bank_dir, entry)))
        if sim > best_sim:
            best, best_sim = entry, sim
    if best is not None and best_sim >= threshold:
        return best, best_sim
    return None, best_sim


def add_voice(bank_dir: Path, bank: dict, vec, label_hint: str, source: str,
              person_id=None) -> dict:
    vid = f"v_{len(bank['voices'])+1:04d}"
    v = np.asarray(vec, dtype=np.float32)
    np.save(Path(bank_dir) / "emb" / f"{vid}.npy", v / (np.linalg.norm(v) + 1e-9))
    entry = {"id": vid, "person_id": person_id, "label_hint": label_hint,
             "emb": f"emb/{vid}.npy", "sources": [source],
             "created": time.strftime("%Y-%m-%d")}
    bank["voices"].append(entry)
    return entry


def add_person(bank: dict, name: str, aliases=None) -> dict:
    p = {"id": f"p_{len(bank['persons'])+1:04d}", "name": name,
         "aliases": list(aliases or []), "created": time.strftime("%Y-%m-%d")}
    bank["persons"].append(p)
    return p


def load_orgchart(bank_dir: Path):
    """用户自放的 orgchart.json；不存在则空。脚本只读不写，内容不打印。"""
    path = Path(bank_dir) / "orgchart.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("persons", [])


def resolve_person(bank: dict, query: str, orgchart=None, cutoff: float = 0.65):
    """模糊找人：先库内 persons，再 orgchart。命中 orgchart 的人会被引入库内。

    匹配优先级(严格先于宽松，避免 "Test One/Test Two" 这类共前缀误配)：
    库内精确(含别名, 大小写不敏感) → 库内包含 → orgchart 精确/包含 → 全池 difflib 近似。
    返回 (person_dict, how) 或 (None, candidates)。
    """
    q = query.strip().lower()

    def names_of(p):
        return [p.get("name", "")] + list(p.get("aliases", []))

    def exact(p):
        return any(q == n.lower() for n in names_of(p))

    def contains(p):
        return any(q in n.lower() or n.lower() in q for n in names_of(p) if n)

    def score(p):
        return max((difflib.SequenceMatcher(None, q, n.lower()).ratio() for n in names_of(p)),
                   default=0)

    for p in bank["persons"]:
        if exact(p):
            return p, "bank"
    for p in bank["persons"]:
        if contains(p):
            return p, "bank:contains"

    org_entries = [{"name": e.get("name", ""), "aliases": list(e.get("aliases", []))}
                   for e in (orgchart or [])]
    for p in org_entries:
        if p["name"] and (exact(p) or contains(p)):
            return add_person(bank, p["name"], p["aliases"]), "orgchart"

    pool = [(p, "bank") for p in bank["persons"]] + [(p, "orgchart") for p in org_entries]
    best, best_how, best_s = None, None, 0.0
    for p, how in pool:
        s = score(p)
        if s > best_s:
            best, best_how, best_s = p, how, s
    if best is not None and best_s >= cutoff:
        if best_how == "orgchart":
            return add_person(bank, best["name"], best["aliases"]), "orgchart:fuzzy"
        return best, "bank:fuzzy"

    cands = sorted((p for p, _ in pool), key=score, reverse=True)[:3]
    cands = [p for p in cands if score(p) >= cutoff * 0.8]
    return None, cands
