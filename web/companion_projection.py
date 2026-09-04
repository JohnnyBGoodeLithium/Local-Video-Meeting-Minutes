"""Read-only, allowlisted Companion views over canonical meeting and job state."""

from __future__ import annotations

import json
import base64
from pathlib import Path
from typing import Any

import meeting_generation
import meeting_topic_map
from deps import (_current_evidence, _meeting_identity, _minutes_file, _read_json,
                  _source, _video_path)
from job_progress import normalize_job_progress


def _time(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def library_item(mdir: Path) -> dict[str, Any]:
    turns = _read_json(mdir / "transcript.spk.json", [])
    duration = max((_time(turn.get("end")) for turn in turns), default=0.0)
    generation = meeting_generation.load(mdir)
    phase = str(generation.get("phase") or ("ready" if _minutes_file(mdir) else "processing"))
    identity = _meeting_identity(mdir.name)
    meta = _read_json(mdir / "meta.json", {})
    updated = max((path.stat().st_mtime for path in mdir.iterdir() if path.is_file()),
                  default=mdir.stat().st_mtime)
    return {
        "id": mdir.name,
        "title": str(identity.get("title") or mdir.name),
        "content_type": str(identity.get("content_type") or "meeting"),
        "duration": round(duration, 3),
        "status": phase,
        "ready": bool(turns and _minutes_file(mdir)),
        "updated_at": float(meta.get("updated_at") or updated),
    }


def library(meetings_root: Path, *, limit: int = 30) -> list[dict[str, Any]]:
    rows = [library_item(path) for path in meetings_root.iterdir()
            if path.is_dir() and not path.name.startswith(".")] if meetings_root.is_dir() else []
    return sorted(rows, key=lambda row: (row["updated_at"], row["id"]), reverse=True)[:limit]


def library_page(meetings_root: Path, *, limit: int = 20, cursor: str | None = None,
                 query: str = "", content_type: str = "", status: str = "") -> dict[str, Any]:
    """Return one allowlisted page; the opaque cursor contains only the next offset."""
    limit = max(1, min(int(limit), 50))
    try:
        offset = int(base64.urlsafe_b64decode((cursor or "MA==") + "===").decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        offset = 0
    rows = [library_item(path) for path in meetings_root.iterdir()
            if path.is_dir() and not path.name.startswith(".")] if meetings_root.is_dir() else []
    needle = query.strip().casefold()[:120]
    filtered = [row for row in rows
                if (not needle or needle in row["title"].casefold())
                and (not content_type or row["content_type"] == content_type)
                and (not status or (status == "ready" and row["ready"])
                     or (status == "processing" and not row["ready"]))]
    filtered.sort(key=lambda row: (row["updated_at"], row["id"]), reverse=True)
    page = filtered[offset:offset + limit]
    next_offset = offset + len(page)
    next_cursor = (base64.urlsafe_b64encode(str(next_offset).encode("ascii")).decode("ascii")
                   if next_offset < len(filtered) else None)
    return {"items": page, "next_cursor": next_cursor}


def _turn_id_index(value: str) -> int | None:
    if value.startswith("T") and value[1:].isdigit():
        return max(0, int(value[1:]) - 1)
    return None


def evidence_rows(mdir: Path, turns: list[dict]) -> list[dict[str, Any]]:
    evidence = _current_evidence(mdir)
    rows = []
    for claim in (evidence.get("claims") or [])[:80]:
        indexes = [index for index in (claim.get("turn_indexes") or [])
                   if isinstance(index, int) and 0 <= index < len(turns)]
        for turn_id in claim.get("turn_ids") or []:
            index = _turn_id_index(str(turn_id))
            if index is not None and index < len(turns) and index not in indexes:
                indexes.append(index)
        selected = [turns[index] for index in indexes]
        start = min((_time(turn.get("start")) for turn in selected), default=0.0)
        end = max((_time(turn.get("end")) for turn in selected), default=start + 15.0)
        rows.append({
            "id": str(claim.get("id") or ""),
            "text": str(claim.get("text") or "")[:600],
            "kind": str(claim.get("kind") or "discussion"),
            "status": str(claim.get("status") or "informational"),
            "confidence": str(claim.get("confidence") or "unknown"),
            "start": round(start, 3), "end": round(max(start, end), 3),
            "speakers": sorted({str(turn.get("speaker") or "Unknown") for turn in selected}),
        })
    return [row for row in rows if row["id"]]


def people_rows(mdir: Path, turns: list[dict]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for index, turn in enumerate(turns):
        name = str(turn.get("speaker") or "Unknown")[:120]
        row = grouped.setdefault(name, {"name": name, "voice_ids": set(), "moments": [],
                                        "moment_count": 0, "duration": 0.0})
        row["moment_count"] += 1
        row["duration"] += max(0.0, _time(turn.get("end")) - _time(turn.get("start")))
        if turn.get("voice"):
            row["voice_ids"].add(str(turn["voice"]))
        if len(row["moments"]) < 80:
            row["moments"].append({
                "id": f"T{index + 1:06d}", "start": round(_time(turn.get("start")), 3),
                "end": round(_time(turn.get("end")), 3),
                "text": str(turn.get("text") or "")[:800],
            })
    rows = [{"name": row["name"], "voice_ids": sorted(row["voice_ids"]),
             "moment_count": row["moment_count"], "duration": round(row["duration"], 3),
             "needs_confirmation": row["name"].casefold().startswith(("speaker ", "unknown")),
             "moments": row["moments"]} for row in grouped.values()]
    return sorted(rows, key=lambda row: (not row["needs_confirmation"], -row["duration"], row["name"]))


def item(mdir: Path) -> dict[str, Any]:
    base = library_item(mdir)
    turns = _read_json(mdir / "transcript.spk.json", [])
    topic_state, topic_map = meeting_topic_map.load_current_topic_map(mdir)
    topics = [{"id": str(row.get("id") or f"M{index + 1:02d}"),
               "title": str(row.get("title") or "")[:200],
               "summary": str(row.get("summary") or "")[:800],
               "start": _time(row.get("start")), "end": _time(row.get("end"))}
              for index, row in enumerate((topic_map.get("topics") or [])[:30])] if topic_state == "ready" else []
    evidence = evidence_rows(mdir, turns)
    conclusions = [row for row in evidence if row["kind"] in {"decision", "action"}][:20]
    return {**base, "map_state": topic_state,
            "summary": str(topic_map.get("meeting_summary") or "")[:1200], "topics": topics,
            "people": [{key: value for key, value in row.items()
                        if key not in {"moments", "voice_ids"}}
                       for row in people_rows(mdir, turns)],
            "conclusions": conclusions, "evidence": evidence,
            "media": {"audio": (mdir / "audio.wav").is_file(),
                      "video": _video_path(mdir) is not None}}


def chapters(mdir: Path) -> dict[str, Any]:
    state, topic_map = meeting_topic_map.load_current_topic_map(mdir)
    if state != "ready":
        return {"state": state, "chapters": []}
    rows = []
    for index, topic in enumerate((topic_map.get("topics") or [])[:40]):
        ranges = [[round(_time(pair[0]), 3), round(_time(pair[1]), 3)]
                  for pair in (topic.get("ranges") or []) if len(pair) == 2]
        rows.append({
            "id": str(topic.get("id") or f"M{index + 1:02d}"),
            "number": index + 1, "title": str(topic.get("title") or "")[:200],
            "summary": str(topic.get("summary") or "")[:1000],
            "start": round(_time(topic.get("start") if topic.get("start") is not None
                                 else ranges[0][0] if ranges else 0), 3),
            "end": round(_time(topic.get("end") if topic.get("end") is not None
                               else ranges[-1][1] if ranges else 0), 3),
            "ranges": ranges,
        })
    return {"state": "ready", "chapters": rows}


def transcript_page(mdir: Path, *, limit: int = 50, cursor: str | None = None,
                    speaker: str = "", query: str = "") -> dict[str, Any]:
    turns = _read_json(mdir / "transcript.spk.json", [])
    limit = max(1, min(int(limit), 100))
    try:
        offset = max(0, int(base64.urlsafe_b64decode((cursor or "MA==") + "===").decode("ascii")))
    except (ValueError, UnicodeDecodeError):
        offset = 0
    needle = query.strip().casefold()[:120]
    rows = []
    for index, turn in enumerate(turns):
        name = str(turn.get("speaker") or "Unknown")[:120]
        text = str(turn.get("text") or "")[:4000]
        if speaker and name != speaker or needle and needle not in text.casefold():
            continue
        rows.append({"turn_id": str(turn.get("id") or f"T{index + 1:06d}"),
                     "speaker": name, "start": round(_time(turn.get("start")), 3),
                     "end": round(_time(turn.get("end")), 3), "text": text})
    page = rows[offset:offset + limit]
    next_offset = offset + len(page)
    next_cursor = (base64.urlsafe_b64encode(str(next_offset).encode()).decode()
                   if next_offset < len(rows) else None)
    return {"turns": page, "next_cursor": next_cursor, "total": len(rows)}


def person(mdir: Path, name: str) -> dict[str, Any] | None:
    turns = _read_json(mdir / "transcript.spk.json", [])
    return next((row for row in people_rows(mdir, turns) if row["name"] == name), None)


def job(original: dict, all_jobs) -> dict[str, Any]:
    progress = normalize_job_progress(original, all_jobs)
    allowed_outputs = {key: value for key, value in (progress.get("available_outputs") or {}).items()}
    return {
        "id": str(original.get("id") or ""),
        "title": str(original.get("display_name") or original.get("meeting") or "Processing")[:160],
        "status": str(original.get("status") or progress.get("state") or "queued"),
        "content_type": str(original.get("content_type") or "meeting"),
        "created_at": original.get("created"),
        "what_is_happening": str(progress.get("message_key") or progress.get("phase") or "prepare"),
        "phase": progress.get("phase"), "done": progress.get("done"),
        "total": progress.get("total"), "unit": progress.get("unit"),
        "estimated_remaining": progress.get("estimated_remaining"),
        "ready": allowed_outputs,
        "can_review": any(allowed_outputs.get(key) in {"partial", "ready"}
                          for key in ("transcript", "voice_draft", "final_minutes")),
    }
