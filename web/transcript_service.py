"""Canonical transcript text corrections and compact review projection."""

from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import meeting_artifact as artifact
from meeting_core.transcript_review import SCHEMA as REVIEW_SCHEMA


EDITS_SCHEMA = "meeting-transcript-edits/v1"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _atomic_json(path: Path, value) -> None:
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _format_time(seconds: float) -> str:
    value = int(float(seconds or 0))
    return f"{value // 3600:02d}:{value % 3600 // 60:02d}:{value % 60:02d}"


def _rewrite_markdown(mdir: Path, turns: list[dict]) -> None:
    path = mdir / "transcript.spk.md"
    heading = f"# {mdir.name} 逐字稿(具名)\n\n"
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        marker = next((index for index, line in enumerate(lines)
                       if line.startswith("[") and "] **" in line), None)
        if marker is not None:
            heading = "".join(lines[:marker])
    body = "\n\n".join(
        f"[{_format_time(turn.get('start', 0))}] **{turn.get('speaker') or '未知'}**: "
        f"{turn.get('text') or ''}" for turn in turns)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temp.write_text(heading + body + "\n", encoding="utf-8")
    os.replace(temp, path)


def _snapshot(mdir: Path, operation: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    destination = mdir / ".versions" / f"before-{operation}-{stamp}"
    suffix = 1
    while destination.exists():
        suffix += 1
        destination = mdir / ".versions" / f"before-{operation}-{stamp}-{suffix}"
    destination.mkdir(parents=True)
    copied = []
    for name in ("transcript.spk.json", "transcript.spk.md", "transcript.review.json",
                 "transcript.edits.json"):
        source = mdir / name
        if source.is_file():
            shutil.copy2(source, destination / name)
            copied.append(name)
    _atomic_json(destination / "manifest.json", {
        "schema": "meeting-transcript-edit-backup/v1", "created_at": time.time(),
        "operation": operation, "files": copied,
    })
    return destination


def _record_review_resolution(mdir: Path, index: int, method: str,
                              transcript_revision: str) -> None:
    path = mdir / "transcript.review.json"
    review = _read_json(path, {})
    if review.get("schema") != REVIEW_SCHEMA:
        review = {"schema": REVIEW_SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
                  "state": "ready", "items": [], "summary": {}}
    matched = False
    for item in review.get("items", []):
        if item.get("turn_index") == index and item.get("status") == "needs_review":
            item["status"] = "human_corrected"
            item["resolved_at"] = datetime.now(timezone.utc).isoformat()
            item["resolution_method"] = method
            matched = True
    summary = review.setdefault("summary", {})
    summary["pending"] = sum(item.get("status") == "needs_review"
                             for item in review.get("items", []))
    summary["human_corrected"] = sum(item.get("status") == "human_corrected"
                                     for item in review.get("items", []))
    if not matched:
        summary["human_corrected"] = int(summary.get("human_corrected", 0)) + 1
    review["state"] = "review_needed" if summary["pending"] else "ready"
    review["transcript_revision"] = transcript_revision
    _atomic_json(path, review)


def apply_text_edit(mdir: Path, index: int, text: str, expected_revision: str | None,
                    *, method: str = "human") -> dict:
    mdir = Path(mdir)
    transcript_path = mdir / "transcript.spk.json"
    before_revision = artifact.file_revision(transcript_path)
    if expected_revision and expected_revision != before_revision:
        raise ValueError("逐字稿已变化，请刷新后重新修改")
    turns = _read_json(transcript_path, [])
    if not isinstance(turns, list) or not 0 <= index < len(turns):
        raise IndexError("逐字稿轮次不存在")
    value = " ".join(str(text or "").replace("\u0000", "").split())
    if not 1 <= len(value) <= 4000:
        raise ValueError("修正文本需为 1–4000 个字符")
    original = str(turns[index].get("text") or "")
    if value == original:
        return {"changed": False, "revision": before_revision, "index": index}

    snapshot = _snapshot(mdir, "transcript-edit")
    turns[index]["text"] = value
    _atomic_json(transcript_path, turns)
    _rewrite_markdown(mdir, turns)
    after_revision = artifact.file_revision(transcript_path)
    history_path = mdir / "transcript.edits.json"
    history = _read_json(history_path, {})
    if history.get("schema") != EDITS_SCHEMA:
        history = {"schema": EDITS_SCHEMA, "edits": []}
    history["edits"].append({
        "id": f"E{len(history['edits']) + 1:06d}", "created_at": time.time(),
        "turn_index": index, "turn_id": f"T{index + 1:06d}", "method": method,
        "before_text": original, "after_text": value,
        "before_revision": before_revision, "after_revision": after_revision,
        "snapshot": snapshot.name,
    })
    _atomic_json(history_path, history)
    _record_review_resolution(mdir, index, method, after_revision or "")
    rag = mdir / ".rag"
    if rag.is_dir():
        shutil.rmtree(rag)
    return {"changed": True, "revision": after_revision, "index": index,
            "undo_available": True}


def undo_latest(mdir: Path) -> dict:
    mdir = Path(mdir)
    transcript_path = mdir / "transcript.spk.json"
    history_path = mdir / "transcript.edits.json"
    history = _read_json(history_path, {})
    edits = history.get("edits", []) if history.get("schema") == EDITS_SCHEMA else []
    if not edits:
        raise LookupError("没有可撤销的逐字稿文本修正")
    latest = edits[-1]
    if artifact.file_revision(transcript_path) != latest.get("after_revision"):
        raise ValueError("逐字稿此后已经变化，不能自动撤销这次修正")
    index = int(latest.get("turn_index", -1))
    _snapshot(mdir, "transcript-edit-undo")
    snapshot = mdir / ".versions" / str(latest.get("snapshot") or "")
    if not snapshot.is_dir() or not (snapshot / "transcript.spk.json").is_file():
        raise ValueError("逐字稿修正快照缺失，不能自动撤销")
    for name in ("transcript.spk.json", "transcript.spk.md", "transcript.review.json",
                 "transcript.edits.json"):
        source, destination = snapshot / name, mdir / name
        if source.is_file():
            temp = destination.with_name(f".{destination.name}.undo-{os.getpid()}")
            shutil.copy2(source, temp)
            os.replace(temp, destination)
        elif name in {"transcript.review.json", "transcript.edits.json"}:
            destination.unlink(missing_ok=True)
    rag = mdir / ".rag"
    if rag.is_dir():
        shutil.rmtree(rag)
    return {"ok": True, "index": index, "revision": artifact.file_revision(transcript_path),
            "undo_available": bool(_read_json(history_path, {}).get("edits", []))}


def project_review(mdir: Path, evidence_current: bool) -> dict:
    mdir = Path(mdir)
    transcript_revision = artifact.file_revision(mdir / "transcript.spk.json")
    review = _read_json(mdir / "transcript.review.json", {})
    history = _read_json(mdir / "transcript.edits.json", {})
    items = review.get("items", []) if review.get("schema") == REVIEW_SCHEMA else []
    pending = [{
        "id": str(item.get("id") or ""), "turn_index": item.get("turn_index"),
        "turn_id": item.get("turn_id"), "start": item.get("start"), "end": item.get("end"),
        "reason": item.get("reason"), "original_text": item.get("original_text"),
        "suggested_text": item.get("suggested_text"),
    } for item in items if item.get("status") == "needs_review"]
    auto_count = sum(item.get("status") == "auto_corrected" for item in items)
    human_count = len(history.get("edits", [])) if history.get("schema") == EDITS_SCHEMA else 0
    return {
        "schema": REVIEW_SCHEMA, "state": "review_needed" if pending else "ready",
        "transcript_revision": transcript_revision,
        "summary": {"auto_corrected": auto_count, "pending": len(pending),
                    "human_corrected": human_count},
        "pending": pending,
        "undo_available": bool(human_count),
        "downstream_state": "current" if evidence_current else "sync_pending",
    }
