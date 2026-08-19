"""Audio-grounded transcript review without downstream-LLM circularity.

Version 1 deliberately targets only confirmed terminology confusions.  It does
not pretend that text fluency is acoustic confidence.  A candidate is changed
automatically only when a second decode of the same audio span contains the
confirmed canonical term; otherwise it remains a small human-review item.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from meeting_core.terminology import load_store


SCHEMA = "meeting-transcript-review/v1"
MAX_CANDIDATES = 12
CLIP_PADDING_SECONDS = 3.5


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _revision(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else None


def _key(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value).casefold())


def _confirmed_confusions(bank_dir: Path, template_path: Path | None = None) -> list[dict]:
    store = load_store(bank_dir, template_path=template_path)
    output = []
    for term in store.get("terms", []):
        canonical = " ".join(str(term.get("canonical") or "").split())
        confusions = [" ".join(str(item).split()) for item in term.get("confusions", [])
                      if str(item).strip()]
        if term.get("status") == "confirmed" and canonical and confusions:
            output.append({"id": str(term.get("id") or _key(canonical)),
                           "canonical": canonical, "confusions": confusions})
    return output


def find_candidates(text: str, stamps: list[dict], terms: list[dict],
                    *, limit: int = MAX_CANDIDATES) -> list[dict]:
    """Locate exact confirmed confusion phrases and bind them to audio spans."""
    joined = "".join(str(item.get("text") or "") for item in stamps)
    if not joined or not stamps:
        return []
    offsets, cursor = [], 0
    for index, item in enumerate(stamps):
        value = str(item.get("text") or "")
        offsets.append((cursor, cursor + len(value), index))
        cursor += len(value)
    found = []
    for term in terms:
        for confusion in term.get("confusions", []):
            if not confusion:
                continue
            joined_matches = list(re.finditer(re.escape(confusion), joined, flags=re.I))
            text_matches = list(re.finditer(re.escape(confusion), text, flags=re.I))
            for ordinal, match in enumerate(joined_matches):
                if ordinal >= len(text_matches):
                    continue
                text_match = text_matches[ordinal]
                overlapping = [index for start, end, index in offsets
                               if end > match.start() and start < match.end()]
                if not overlapping:
                    continue
                first, last = overlapping[0], overlapping[-1]
                start = float(stamps[first].get("start_time", 0))
                end = float(stamps[last].get("end_time", start))
                candidate_id = hashlib.sha256(
                    f"{term['id']}|{start:.3f}|{end:.3f}|{confusion}".encode()).hexdigest()[:16]
                found.append({
                    "id": f"R{candidate_id}", "term_id": term["id"],
                    "canonical": term["canonical"], "confusion": confusion,
                    "text_start": text_match.start(), "text_end": text_match.end(),
                    "stamp_text_start": match.start(), "stamp_text_end": match.end(),
                    "stamp_start": first, "stamp_end": last,
                    "start": start, "end": end,
                    "reason": "confirmed_term_confusion",
                })
    found.sort(key=lambda item: (-len(item["confusion"]), item["start"], item["id"]))
    chosen = []
    for item in found:
        if any(not (item["text_end"] <= other["text_start"]
                        or item["text_start"] >= other["text_end"])
               for other in chosen):
            continue
        chosen.append(item)
        if len(chosen) >= limit:
            break
    return sorted(chosen, key=lambda item: item["text_start"])


def _context_for(candidate: dict, text: str, base_context: str) -> str:
    start = max(0, candidate["text_start"] - 260)
    end = min(len(text), candidate["text_end"] + 260)
    return (str(base_context or "")[:1800] + "\n"
            "请重新忠实转写这段原语言音频，不翻译、不补写。"
            f"已确认企业术语：{candidate['canonical']}。只有声音相符时才采用。\n"
            f"相邻第一次转写（只作上下文，可能含错词）：{text[start:end]}")[:2400]


def _replace_stamp_range(stamps: list[dict], candidate: dict, replacement: str) -> None:
    """Replace the exact confusion characters while preserving original timing."""
    start_index, end_index = candidate["stamp_start"], candidate["stamp_end"]
    before = sum(len(str(item.get("text") or "")) for item in stamps[:start_index])
    local_start = candidate["stamp_text_start"] - before
    if start_index == end_index:
        value = str(stamps[start_index].get("text") or "")
        local_end = candidate["stamp_text_end"] - before
        stamps[start_index]["text"] = value[:local_start] + replacement + value[local_end:]
        return
    first = str(stamps[start_index].get("text") or "")
    stamps[start_index]["text"] = first[:local_start] + replacement
    consumed_before_last = sum(
        len(str(item.get("text") or "")) for item in stamps[:end_index])
    last = str(stamps[end_index].get("text") or "")
    local_end = candidate["stamp_text_end"] - consumed_before_last
    stamps[end_index]["text"] = last[local_end:]
    for index in range(start_index + 1, end_index):
        stamps[index]["text"] = ""


def review_term_confusions(provider, audio_path: Path, text: str, stamps: list[dict],
                           base_context: str, bank_dir: Path,
                           *, language: str | None = None,
                           template_path: Path | None = None) -> tuple[str, list[dict], dict]:
    """Run one batched targeted re-decode and return corrected canonical material."""
    terms = _confirmed_confusions(bank_dir, template_path=template_path)
    candidates = find_candidates(text, stamps, terms)
    if not candidates:
        return text, stamps, {
            "schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
            "state": "clean", "provider": getattr(provider, "name", "unknown"),
            "items": [], "summary": {"checked": 0, "auto_corrected": 0, "pending": 0},
        }

    import soundfile as sf
    samples, sample_rate = sf.read(str(audio_path), dtype="float32", always_2d=False)
    if getattr(samples, "ndim", 1) > 1:
        samples = samples.mean(axis=1)
    clips, contexts = [], []
    for item in candidates:
        clip_start = max(0.0, item["start"] - CLIP_PADDING_SECONDS)
        clip_end = min(len(samples) / sample_rate, item["end"] + CLIP_PADDING_SECONDS)
        clips.append((samples[int(clip_start * sample_rate):int(clip_end * sample_rate)], sample_rate))
        contexts.append(_context_for(item, text, base_context))
        item["clip_start"], item["clip_end"] = round(clip_start, 3), round(clip_end, 3)

    results = provider.transcribe(clips, context=contexts, language=language,
                                  return_time_stamps=False)
    accepted = []
    for item, result in zip(candidates, results):
        rerun = " ".join(str(result.text or "").split())
        confirmed = (_key(item["canonical"]) in _key(rerun)
                     and _key(item["confusion"]) not in _key(rerun))
        item["status"] = "auto_corrected" if confirmed else "needs_review"
        item["original_text"] = item["confusion"]
        item["suggested_text"] = item["canonical"]
        item["rerun_text"] = rerun
        item["context_applied"] = bool(result.context_applied)
        if confirmed:
            accepted.append(item)

    corrected_text = text
    corrected_stamps = [dict(item) for item in stamps]
    for item in sorted(accepted, key=lambda value: value["text_start"], reverse=True):
        corrected_text = (corrected_text[:item["text_start"]] + item["canonical"]
                          + corrected_text[item["text_end"]:])
        _replace_stamp_range(corrected_stamps, item, item["canonical"])

    pending = sum(item["status"] == "needs_review" for item in candidates)
    document = {
        "schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
        "state": "review_needed" if pending else "ready",
        "provider": getattr(provider, "name", "unknown"),
        "policy": {
            "downstream_llm_rewrites_transcript": False,
            "automatic_change_requires_audio_redecode": True,
            "inline_warning_limit": 0,
        },
        "items": candidates,
        "summary": {"checked": len(candidates), "auto_corrected": len(accepted),
                    "pending": pending},
    }
    return corrected_text, corrected_stamps, document


def safe_review_term_confusions(*args, **kwargs):
    """Enhancement failure never blocks the baseline transcription."""
    try:
        return review_term_confusions(*args, **kwargs)
    except Exception as exc:
        text, stamps = args[2], args[3]
        return text, stamps, {
            "schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
            "state": "unavailable", "error_type": type(exc).__name__, "items": [],
            "summary": {"checked": 0, "auto_corrected": 0, "pending": 0},
        }


def write_review(path: Path, document: dict) -> None:
    _atomic_json(path, document)


def bind_review_to_transcript(mdir: Path) -> dict:
    """Attach review spans to stable current turn indexes after diarization merge."""
    mdir = Path(mdir)
    path = mdir / "transcript.review.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        turns = json.loads((mdir / "transcript.spk.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    if document.get("schema") != SCHEMA or not isinstance(turns, list):
        return {}
    for item in document.get("items", []):
        midpoint = (float(item.get("start", 0)) + float(item.get("end", 0))) / 2
        index = next((i for i, turn in enumerate(turns)
                      if float(turn.get("start", 0)) <= midpoint <= float(turn.get("end", 0))), None)
        if index is None and turns:
            index = min(range(len(turns)), key=lambda i: abs(float(turns[i].get("start", 0)) - midpoint))
        item["turn_index"] = index
        item["turn_id"] = f"T{index + 1:06d}" if index is not None else None
    document["transcript_revision"] = _revision(mdir / "transcript.spk.json")
    _atomic_json(path, document)
    return document
