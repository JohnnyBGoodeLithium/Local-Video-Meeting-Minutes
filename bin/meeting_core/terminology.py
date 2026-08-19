"""会议术语库、ASR context pack 与屏幕术语候选。

已确认词表和重复出现的高置信屏幕候选可进入下一场会议的 ASR context；
单场模型候选永远不会自动改写逐字稿，也不会直接晋升为团队词表。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from meeting_core.llm import LocalLLMClient


STORE_SCHEMA = "meeting-terminology/v1"
CANDIDATE_SCHEMA = "meeting-terminology-candidates/v1"
CONTEXT_SCHEMA = "meeting-asr-context/v1"
MAX_CONTEXT_CHARS = 2400
MAX_SCREEN_INPUT_CHARS = 18000


def configured_bank_dir(code_root: Path) -> Path:
    """解析私有词表目录；兼容 Web 旧变量与独立数据根部署。"""
    explicit = os.environ.get("MEETING_BANK_DIR") or os.environ.get("MEETING_WEB_BANK")
    if explicit:
        return Path(explicit).expanduser()
    data_root = Path(os.environ.get(
        "MEETING_DATA_ROOT", os.environ.get("MEETING_MINUTES_ROOT", code_root)))
    return data_root.expanduser() / "speaker_bank"


def _read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _atomic_json(path: Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _key(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value).casefold())


def _valid_term(value: object) -> bool:
    text = " ".join(str(value or "").split()).strip(" -—:：,，.;；")
    if not 2 <= len(text) <= 80:
        return False
    return bool(re.search(r"[A-Za-z\u4e00-\u9fff]", text))


def load_store(bank_dir: Path, template_path: Path | None = None) -> dict:
    """读取私有词表；不存在时使用仓库模板，但不擅自写入私有文件。"""
    bank_dir = Path(bank_dir)
    private = _read_json(bank_dir / "terminology.json", {})
    if private.get("schema") == STORE_SCHEMA and isinstance(private.get("terms"), list):
        return private
    template = template_path or bank_dir / "terminology.template.json"
    value = _read_json(template, {})
    if value.get("schema") != STORE_SCHEMA or not isinstance(value.get("terms"), list):
        return {"schema": STORE_SCHEMA, "terms": []}
    return value


def _reusable_candidates(bank_dir: Path) -> list[dict]:
    value = _read_json(Path(bank_dir) / "terminology.candidates.json", {})
    if value.get("schema") != CANDIDATE_SCHEMA:
        return []
    reusable = []
    for term in value.get("terms", []):
        meetings = {str(item) for item in term.get("source_meetings", []) if str(item)}
        if (term.get("status") == "confirmed"
                or (term.get("confidence") == "high" and len(meetings) >= 2)):
            reusable.append(term)
    return reusable


def build_context(title: str, bank_dir: Path, *, max_chars: int = MAX_CONTEXT_CHARS,
                  template_path: Path | None = None) -> tuple[str, list[dict]]:
    """构建只含标题与术语的 ASR 提示，不复制历史逐字稿。"""
    store = load_store(bank_dir, template_path=template_path)
    terms = [item for item in store.get("terms", [])
             if item.get("status") == "confirmed" and _valid_term(item.get("canonical"))]
    known = {_key(item.get("canonical", "")) for item in terms}
    for item in _reusable_candidates(bank_dir):
        if _valid_term(item.get("canonical")) and _key(item.get("canonical", "")) not in known:
            terms.append(item)
            known.add(_key(item.get("canonical", "")))

    header = [
        "你正在转写一场企业内部会议。严格忠实于音频，不补写未说内容。",
        "保留中英文混说、英文缩写、产品名、区域名和财务术语的标准拼写。",
        f"会议主题：{' '.join(str(title or '未命名会议').split())}",
        "已知术语（仅在声学和语义都匹配时采用）：",
    ]
    selected = []
    for item in terms:
        canonical = " ".join(str(item.get("canonical") or "").split())
        aliases = [" ".join(str(x).split()) for x in item.get("aliases", []) if _valid_term(x)]
        meaning = " ".join(str(item.get("meaning") or "").split())[:180]
        line = f"- {canonical}"
        if aliases:
            line += f"；别名：{', '.join(aliases[:5])}"
        if meaning:
            line += f"；含义：{meaning}"
        confusions = [" ".join(str(x).split()) for x in item.get("confusions", []) if str(x).strip()]
        if confusions:
            line += f"；易误听为：{', '.join(confusions[:3])}（不要脱离语境强制替换）"
        if len("\n".join(header + [line])) > max_chars:
            break
        header.append(line)
        selected.append({
            "id": str(item.get("id") or _key(canonical)),
            "canonical": canonical,
            "status": str(item.get("status") or "candidate"),
        })
    return "\n".join(header), selected


def write_context_pack(mdir: Path, title: str, bank_dir: Path,
                       *, template_path: Path | None = None) -> tuple[str, dict]:
    context, selected = build_context(title, bank_dir, template_path=template_path)
    document = {
        "schema": CONTEXT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": " ".join(str(title or "").split()),
        "context_sha256": hashlib.sha256(context.encode("utf-8")).hexdigest(),
        "term_count": len(selected),
        "terms": selected,
        "policy": {
            "single_meeting_candidates_are_reusable": False,
            "repeated_high_confidence_meetings_required": 2,
            "rewrites_transcript": False,
        },
    }
    _atomic_json(Path(mdir) / "asr.context.json", document)
    return context, document


def _screen_material(mdir: Path, title: str) -> str:
    cache = _read_json(Path(mdir) / "page_desc.json", {})
    desc = cache.get("desc", {}) if isinstance(cache, dict) else {}
    chunks = [f"会议主题：{' '.join(str(title or '').split())}"]
    for key in sorted(desc, key=lambda value: int(value) if str(value).isdigit() else 10**9):
        text = " ".join(str(desc[key] or "").split())
        if not text:
            continue
        chunks.append(f"页面{key}：{text[:900]}")
        if len("\n".join(chunks)) >= MAX_SCREEN_INPUT_CHARS:
            break
    return "\n".join(chunks)[:MAX_SCREEN_INPUT_CHARS]


def _json_object(text: str) -> dict:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        value = json.loads(cleaned[start:end + 1])
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def harvest_screen_candidates(mdir: Path, title: str, bank_dir: Path,
                              *, client: LocalLLMClient | None = None) -> dict:
    """从已完成的共享画面说明提取候选；只落候选库，不改逐字稿或确认词表。"""
    material = _screen_material(mdir, title)
    if "页面" not in material:
        return {"added": 0, "updated": 0, "total": 0, "state": "no_screen_material"}
    prompt = """从以下会议主题和共享画面说明中提取下一次语音识别值得提示的企业术语。
只保留画面中明确出现的英文缩写、产品/项目名、区域名、指标名和专业词；不要提取普通词、人名、
完整句子或仅由你推断的概念。返回严格 JSON：
{"terms":[{"canonical":"标准写法","meaning":"不超过40字的含义","category":"region|product|metric|project|other","confidence":"high|medium"}]}
最多 30 条。没有则返回 {"terms":[]}。

资料：
""" + material
    llm = client or LocalLLMClient(
        model=os.environ.get("MEETING_TERMINOLOGY_MODEL",
                             os.environ.get("MEETING_LLM_MODEL", "qwen3.6-35b-a3b-operator")))
    parsed = _json_object(llm.complete(prompt, max_tokens=1600, temperature=0.0).content)
    raw_terms = parsed.get("terms", []) if isinstance(parsed.get("terms"), list) else []
    path = Path(bank_dir) / "terminology.candidates.json"
    current = _read_json(path, {})
    if current.get("schema") != CANDIDATE_SCHEMA:
        current = {"schema": CANDIDATE_SCHEMA, "updated_at": None, "terms": []}
    by_key = {_key(item.get("canonical", "")): item for item in current.get("terms", [])
              if _key(item.get("canonical", ""))}
    added = updated = 0
    meeting_key = hashlib.sha256(Path(mdir).name.encode("utf-8")).hexdigest()[:16]
    for raw in raw_terms[:30]:
        if not isinstance(raw, dict) or not _valid_term(raw.get("canonical")):
            continue
        canonical = " ".join(str(raw["canonical"]).split())
        key = _key(canonical)
        if key in by_key:
            item = by_key[key]
            sources = item.setdefault("source_meetings", [])
            if meeting_key not in sources:
                sources.append(meeting_key)
                updated += 1
            if raw.get("confidence") == "high":
                item["confidence"] = "high"
        else:
            item = {
                "id": f"auto-{hashlib.sha256(key.encode()).hexdigest()[:12]}",
                "canonical": canonical,
                "meaning": " ".join(str(raw.get("meaning") or "").split())[:80],
                "category": str(raw.get("category") or "other"),
                "confidence": "high" if raw.get("confidence") == "high" else "medium",
                "status": "candidate",
                "source": "screen",
                "source_meetings": [meeting_key],
            }
            current["terms"].append(item)
            by_key[key] = item
            added += 1
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(path, current)
    return {"added": added, "updated": updated, "total": len(current["terms"]),
            "state": "ready"}


def safe_harvest_screen_candidates(mdir: Path, title: str, bank_dir: Path,
                                   *, client: LocalLLMClient | None = None) -> dict:
    """失败隔离包装：术语候选是后处理资产，绝不能让正式纪要失败。"""
    try:
        return harvest_screen_candidates(mdir, title, bank_dir, client=client)
    except Exception as exc:
        return {
            "added": 0,
            "updated": 0,
            "total": 0,
            "state": "failed",
            "error_type": type(exc).__name__,
        }
