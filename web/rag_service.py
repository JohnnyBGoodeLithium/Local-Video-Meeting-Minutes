"""会议级证据检索。

不调用模型，也不写会议文件。检索层把当前会议的纪要结论、逐字稿、页面理解和
纪要章节组织成同一个可引用结果集，供本地 LLM 做 RAG 回答，也供调试接口检查
“为什么召回了这些证据”。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path


RAG_VERSION = "meeting-rag/evidence-hybrid-v1"
MAX_RESULTS = 18


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _revision(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _minutes_file(mdir: Path) -> Path | None:
    return next((mdir / name for name in ("minutes.md", "minutes.spk.md")
                 if (mdir / name).is_file()), None)


def _terms(text: str) -> list[str]:
    """英文按词、中文按单字+双字切分，避免依赖外部分词或 embedding 服务。"""
    value = str(text or "").lower()
    out = re.findall(r"[a-z0-9][a-z0-9_.-]*", value)
    for run in re.findall(r"[\u3400-\u9fff]+", value):
        out.extend(run)
        out.extend(run[i:i + 2] for i in range(len(run) - 1))
    return out


def _clean_markdown(value: str) -> str:
    value = re.sub(r"<!--\s*mm:evidence\s+.*?-->", "", value, flags=re.S)
    value = re.sub(r"!\[[^]]*]\([^)]*\)", "", value)
    value = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", value)
    value = value.replace("**", "").replace("__", "").replace("`", "")
    value = re.sub(r"^[\s>*#-]+", "", value, flags=re.M)
    return " ".join(value.split()).strip()


def _minutes_sections(minutes: str) -> list[dict]:
    headings = list(re.finditer(r"^(#{1,6})\s+(.+?)\s*$", minutes, re.M))
    records = []
    for pos, heading in enumerate(headings):
        level = len(heading.group(1))
        end = len(minutes)
        for later in headings[pos + 1:]:
            if len(later.group(1)) <= level:
                end = later.start()
                break
        text = _clean_markdown(minutes[heading.end():end])
        if text:
            records.append({
                "source_id": f"S{len(records) + 1:04d}",
                "type": "minutes_section",
                "text": text,
                "section": heading.group(2).strip(),
                "level": level,
                "evidence_ids": [],
                "turn_indexes": [],
            })
    return records


def _valid_evidence(mdir: Path, minutes_path: Path | None) -> dict:
    evidence = _read_json(mdir / "minutes.evidence.json", {})
    if not evidence or minutes_path is None:
        return {}
    revisions = evidence.get("revisions", {})
    if revisions.get("transcript") != _revision(mdir / "transcript.spk.json"):
        return {}
    if revisions.get("minutes") != _revision(minutes_path):
        return {}
    return evidence


def meeting_records(mdir: Path) -> tuple[list[dict], dict]:
    """读取当前 revision 的证据；旧会议无 claim marker 时仍可检索原文与纪要章节。"""
    mdir = Path(mdir)
    minutes_path = _minutes_file(mdir)
    minutes = minutes_path.read_text(encoding="utf-8") if minutes_path else ""
    evidence = _valid_evidence(mdir, minutes_path)
    turns = (evidence.get("sources", {}).get("transcript", [])
             or _read_json(mdir / "transcript.spk.json", []))
    records: list[dict] = []

    turn_by_id: dict[str, dict] = {}
    for index, turn in enumerate(turns):
        source_id = str(turn.get("id") or f"T{index + 1:06d}")
        row = {
            "source_id": source_id,
            "type": "transcript",
            "text": str(turn.get("text") or ""),
            "speaker": str(turn.get("speaker") or "未知"),
            "start": float(turn.get("start") or 0),
            "end": float(turn.get("end") or turn.get("start") or 0),
            "turn_indexes": [int(turn.get("index", index))],
            "evidence_ids": [source_id],
            "page_id": turn.get("page_id"),
        }
        turn_by_id[source_id] = row
        records.append(row)

    for claim in evidence.get("claims", []):
        turn_ids = [str(value) for value in claim.get("turn_ids", [])]
        linked = [turn_by_id[value] for value in turn_ids if value in turn_by_id]
        records.append({
            "source_id": str(claim.get("id") or f"C{len(records) + 1:05d}"),
            "type": "claim",
            "text": str(claim.get("text") or ""),
            "section": str(claim.get("section") or ""),
            "kind": str(claim.get("kind") or "discussion"),
            "status": str(claim.get("status") or "informational"),
            "confidence": str(claim.get("confidence") or "medium"),
            "turn_indexes": [item["turn_indexes"][0] for item in linked],
            "evidence_ids": [*turn_ids, *map(str, claim.get("page_ids", []))],
            "start": min((item["start"] for item in linked), default=claim.get("start")),
            "end": max((item["end"] for item in linked), default=claim.get("end")),
            "speakers": list(dict.fromkeys(item["speaker"] for item in linked)),
        })

    page_rows = evidence.get("sources", {}).get("pages", [])
    if not page_rows:
        descriptions = _read_json(mdir / "page_desc.json", {}).get("desc", {})
        slides = _read_json(mdir / "slides.json", [])
        page_rows = [{
            "id": f"P{int(page['page']):04d}",
            "number": int(page["page"]),
            "first": float(page.get("first") or 0),
            "visual_description": str(descriptions.get(str(page["page"]), "")),
            "discussion_turn_ids": [],
            "display_status": "display_only",
        } for page in slides if page.get("kind", "slide") == "slide" and page.get("page") is not None]
    for page in page_rows:
        text = str(page.get("visual_description") or "").strip()
        if not text:
            continue
        linked = [turn_by_id[value] for value in page.get("discussion_turn_ids", [])
                  if value in turn_by_id]
        records.append({
            "source_id": str(page.get("id") or f"P{int(page.get('number', 0)):04d}"),
            "type": "slide",
            "text": text,
            "page_number": int(page.get("number") or 0),
            "display_status": str(page.get("display_status") or "display_only"),
            "start": float(page.get("first") or 0),
            "end": float(page.get("first") or 0),
            "turn_indexes": [item["turn_indexes"][0] for item in linked],
            "evidence_ids": [str(page.get("id") or ""),
                             *map(str, page.get("discussion_turn_ids", []))],
        })

    records.extend(_minutes_sections(minutes))
    evidence_state = ("ready" if evidence.get("claims") else
                      "partial" if evidence else "fallback")
    return [record for record in records if record.get("text")], {
        "version": RAG_VERSION,
        "evidence_state": evidence_state,
        "claim_count": len(evidence.get("claims", [])),
    }


def _intent_boost(query: str, record: dict) -> float:
    q = query.lower()
    rtype = record["type"]
    boost = {"claim": 1.22, "transcript": 1.0, "slide": 0.82,
             "minutes_section": 0.92}.get(rtype, 1.0)
    if re.search(r"决定|结论|批准|通过|共识|decision|approve", q):
        if rtype == "claim":
            boost *= 1.35 if record.get("kind") in {"decision", "alignment"} else 1.12
    if re.search(r"行动|待办|谁负责|截止|follow.?up|action|owner|deadline", q):
        if rtype == "claim" and record.get("kind") == "action":
            boost *= 1.5
    if re.search(r"ppt|页面|幻灯片|图表|deck|slide", q) and rtype == "slide":
        boost *= 1.55
    if re.search(r"谁说|原话|逐字|什么时候说|who said|quote", q) and rtype == "transcript":
        boost *= 1.45
    return boost


def _rank(records: list[dict], query: str) -> list[dict]:
    query_terms = Counter(_terms(query))
    if not query_terms:
        return []
    tokenized = [_terms(f"{record.get('section', '')} {record.get('speaker', '')} "
                        f"{record.get('text', '')}") for record in records]
    document_frequency = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))
    total = len(records)
    average_length = sum(map(len, tokenized)) / max(total, 1)
    ranked = []
    for record, tokens in zip(records, tokenized):
        counts = Counter(tokens)
        length = max(len(tokens), 1)
        score = 0.0
        for term, query_count in query_terms.items():
            tf = counts.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (total - document_frequency[term] + 0.5)
                            / (document_frequency[term] + 0.5))
            denom = tf + 1.2 * (0.25 + 0.75 * length / max(average_length, 1))
            score += idf * (tf * 2.2 / denom) * (1 + math.log1p(query_count))
        phrase = query.strip().lower()
        hay = f"{record.get('section', '')} {record.get('text', '')}".lower()
        if len(phrase) >= 3 and phrase in hay:
            score += 5.0
        if score > 0:
            ranked.append({**record, "_score": score * _intent_boost(query, record)})
    return sorted(ranked, key=lambda item: item["_score"], reverse=True)


def retrieve(mdir: Path, query: str, explicit_turn_indexes: list[int] | None = None,
             limit: int = MAX_RESULTS) -> dict:
    records, meta = meeting_records(mdir)
    explicit = sorted(set(explicit_turn_indexes or []))
    transcript_count = sum(record["type"] == "transcript" for record in records)
    if explicit and (explicit[0] < 0 or explicit[-1] >= transcript_count):
        raise ValueError("逐字稿引用已失效，请重新选择")

    chosen: list[dict] = []
    seen: set[str] = set()

    def add(record: dict):
        key = f"{record['type']}:{record['source_id']}"
        if key not in seen:
            seen.add(key)
            chosen.append(record)

    if explicit:
        expanded = set(explicit)
        for index in explicit:
            if index:
                expanded.add(index - 1)
            if index + 1 < transcript_count:
                expanded.add(index + 1)
        wanted_ids = {f"T{index + 1:06d}" for index in expanded}
        for record in records:
            if record["type"] == "transcript" and record["source_id"] in wanted_ids:
                add(record)
        explicit_ids = {f"T{index + 1:06d}" for index in explicit}
        for record in records:
            if record["type"] in {"claim", "slide"} and explicit_ids.intersection(
                    record.get("evidence_ids", [])):
                add(record)

    caps = {"claim": 5, "transcript": 10, "slide": 4, "minutes_section": 3}
    counts = Counter(record["type"] for record in chosen)
    for record in _rank(records, query):
        if len(chosen) >= max(1, min(limit, MAX_RESULTS)):
            break
        if counts[record["type"]] >= caps.get(record["type"], 3):
            continue
        before = len(chosen)
        add(record)
        if len(chosen) > before:
            counts[record["type"]] += 1

    if not chosen:
        for record in records:
            if record["type"] == "minutes_section":
                add(record)
                break
        for record in records:
            if record["type"] == "transcript" and len(chosen) < 5:
                add(record)

    # Claim/页面命中后同时带回少量原始逐字稿，避免模型只看到二次归纳。
    by_source_id = {record["source_id"]: record for record in records}
    expanded: list[dict] = []
    expanded_seen: set[str] = set()
    for record in chosen:
        key = f"{record['type']}:{record['source_id']}"
        if key not in expanded_seen and len(expanded) < limit:
            expanded_seen.add(key)
            expanded.append(record)
        if record["type"] not in {"claim", "slide"}:
            continue
        added = 0
        for evidence_id in record.get("evidence_ids", []):
            support = by_source_id.get(evidence_id)
            if not support or support["type"] != "transcript":
                continue
            support_key = f"transcript:{support['source_id']}"
            if support_key in expanded_seen:
                continue
            if len(expanded) >= limit or added >= 2:
                break
            expanded_seen.add(support_key)
            expanded.append(support)
            added += 1

    sources, blocks = [], []
    names = {"claim": "纪要结论", "transcript": "逐字稿", "slide": "页面",
             "minutes_section": "纪要章节"}
    for number, record in enumerate(expanded[:limit], 1):
        citation_id = f"R{number}"
        source = {key: value for key, value in record.items() if not key.startswith("_")}
        source.update({
            "id": citation_id,
            "label": names.get(record["type"], "资料"),
            "excerpt": str(record["text"])[:360],
        })
        sources.append(source)
        detail = []
        if record.get("section"):
            detail.append(str(record["section"]))
        if record.get("speaker"):
            detail.append(str(record["speaker"]))
        if record.get("start") is not None:
            detail.append(f"{float(record['start']):.1f}s")
        if record.get("page_number"):
            detail.append(f"第{record['page_number']}页")
        if record.get("status"):
            detail.append(str(record["status"]))
        blocks.append(f"【{citation_id}｜{names.get(record['type'], '资料')}"
                      f"{'｜' + '｜'.join(detail) if detail else ''}】\n{record['text']}")
    return {**meta, "records": len(records), "sources": sources,
            "context": "\n\n".join(blocks)}
