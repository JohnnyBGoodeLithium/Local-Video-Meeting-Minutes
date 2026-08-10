"""声纹库读写/比对共享模块（teams_minutes.py 与 voice_tool.py 共用）。

库结构 v3（speaker_bank/）：
    bank.json   {"persons": [{id,name,display_name,names,aliases,created}], "voices": [...]}
    emb/v_XXXX.npy   每条声纹的质心向量(L2 归一化)
    orgchart.json    用户自放的 BU 架构(可选)，只被本地脚本读取——云端 agent 不读。

设计：人(person) 与 声纹(voice) 分离。一个人可挂多条声纹(聚类过拆/音色变化)，
匹配在声纹层做(取最大相似度)，显示名取 person.display_name，未绑定显示 label_hint。
一名人员可有中文名、全拼、英文名+姓氏等多个经过确认的名称；近似名称只给候选，
永远不能自动绑定。
"""

import difflib
import json
import time
import unicodedata
from pathlib import Path

import numpy as np

SCHEMA = 3
NAME_TYPES = {"org", "chinese", "pinyin", "english_display", "other"}


def normalize_name(value: str) -> str:
    """用于已确认名称的等价比较：统一字符/大小写/空白和常见分隔符。"""
    value = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    value = " ".join(value.split())
    return value


def _person_names(person: dict) -> list[dict]:
    """兼容旧 aliases，并返回去重后的类型化名称。"""
    out, seen = [], set()
    raw = list(person.get("names") or [])
    # 用户明确设置的类型优先；兼容字段只在缺失时兜底。
    raw.append({"value": person.get("name", ""), "type": "org", "verified": True})
    raw.append({"value": person.get("display_name", ""),
                "type": "english_display", "verified": True})
    raw += [{"value": a, "type": "other", "verified": True}
            for a in person.get("aliases", [])]
    for item in raw:
        if isinstance(item, str):
            item = {"value": item, "type": "other", "verified": True}
        value = str(item.get("value", "")).strip()
        key = normalize_name(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"value": value,
                    "type": item.get("type") if item.get("type") in NAME_TYPES else "other",
                    "verified": bool(item.get("verified", True))})
    return out


def normalize_person(person: dict) -> dict:
    person["name"] = str(person.get("name") or person.get("display_name") or "").strip()
    person["display_name"] = str(person.get("display_name") or person["name"]).strip()
    person["names"] = _person_names(person)
    person["aliases"] = [n["value"] for n in person["names"]
                           if normalize_name(n["value"]) != normalize_name(person["name"])]
    return person


def load_bank(bank_dir: Path) -> dict:
    path = Path(bank_dir) / "bank.json"
    if not path.is_file():
        return {"schema": SCHEMA, "persons": [], "voices": []}
    raw_text = path.read_text(encoding="utf-8")
    bank = json.loads(raw_text)
    schema = bank.get("schema", 1)
    if isinstance(schema, int) and schema > SCHEMA:
        raise ValueError(f"不支持更新的声纹库 schema: {schema}")
    if schema == 1:  # v1: voices 带 name 字段, 无 persons
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
        bank = {"schema": 2, "persons": persons, "voices": voices}
    changed = bank.get("schema") != SCHEMA
    for person in bank.get("persons", []):
        before = json.dumps(person, ensure_ascii=False, sort_keys=True)
        normalize_person(person)
        changed = changed or before != json.dumps(person, ensure_ascii=False, sort_keys=True)
    bank["schema"] = SCHEMA
    if changed:
        if schema != SCHEMA:
            backup = Path(bank_dir) / "bank.pre-v3.backup.json"
            if not backup.exists():
                backup.write_text(raw_text, encoding="utf-8")
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
            return p.get("display_name") or p["name"]
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


def add_person(bank: dict, name: str, aliases=None, *, display_name=None,
               names=None, name_type="other") -> dict:
    typed = [{"value": name, "type": name_type, "verified": True}]
    typed += list(names or [])
    typed += [{"value": a, "type": "other", "verified": True} for a in (aliases or [])]
    p = {"id": f"p_{len(bank['persons'])+1:04d}", "name": name,
         "display_name": display_name or name, "names": typed,
         "aliases": list(aliases or []), "created": time.strftime("%Y-%m-%d")}
    normalize_person(p)
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
    """只自动接受唯一的已确认名称精确匹配；包含/近似结果只返回候选。"""
    q = normalize_name(query)

    def names_of(p):
        if "names" in p:
            return [n["value"] for n in _person_names(p) if n.get("verified", True)]
        return [p.get("name", "")] + list(p.get("aliases", []))

    def exact(p):
        return any(q == normalize_name(n) for n in names_of(p))

    def contains(p):
        return any(q in normalize_name(n) or normalize_name(n) in q for n in names_of(p) if n)

    def score(p):
        return max((difflib.SequenceMatcher(None, q, normalize_name(n)).ratio()
                    for n in names_of(p)),
                   default=0)

    bank_exact = [p for p in bank["persons"] if exact(p)]
    if len(bank_exact) == 1:
        return bank_exact[0], "bank:verified-name"
    if len(bank_exact) > 1:
        return None, bank_exact

    org_entries = [{"name": e.get("name", ""),
                    "display_name": e.get("display_name") or e.get("name", ""),
                    "aliases": list(e.get("aliases", [])),
                    "names": list(e.get("names", [])), "_source": "orgchart"}
                   for e in (orgchart or [])]
    org_exact = [p for p in org_entries if p["name"] and exact(p)]
    if len(org_exact) == 1:
        p = org_exact[0]
        return add_person(bank, p["name"], p["aliases"], display_name=p["display_name"],
                          names=p["names"], name_type="org"), "orgchart:verified-name"
    if len(org_exact) > 1:
        return None, org_exact

    pool = [(p, "bank") for p in bank["persons"]] + [(p, "orgchart") for p in org_entries]
    ranked = sorted((p for p, _ in pool if contains(p) or score(p) >= cutoff * 0.8),
                    key=score, reverse=True)[:5]
    cands = [{**p, "_match_score": round(score(p), 3)} for p in ranked]
    return None, cands
