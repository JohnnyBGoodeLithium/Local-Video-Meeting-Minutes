"""Feature-flagged Experimental Live Context HTTP boundary."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import secrets
import json
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from deps import DRY_RUN, MEETINGS, _mdir
from meeting_core.live.audio_capture import probe_host_audio
from meeting_core.live.capabilities import build_capture_plan
from meeting_core.live.captions import TesseractCaptionOCR
from meeting_core.live.runtime import LiveRuntimeError, LiveSessionManager
from meeting_core.live.source import SourceProbeError, probe_live_source


router = APIRouter()
MANAGER = LiveSessionManager()
_recovery_checked = False


def _enabled() -> None:
    if os.environ.get("MEETING_LIVE_CONTEXT") != "1":
        raise HTTPException(404, "Live Context is not enabled")


def _recover_once() -> None:
    global _recovery_checked
    if _recovery_checked:
        return
    _recovery_checked = True
    MANAGER.recover(MEETINGS, dry_run=DRY_RUN)


def _probe(payload: dict):
    content_type = str(payload.get("content_type") or "live_event")
    if content_type not in {"meeting", "live_event"}:
        raise HTTPException(400, "Unsupported live content type")
    source_url = str(payload.get("source_url") or "").strip()
    if not source_url:
        raise HTTPException(400, "A source URL is required")
    try:
        source = probe_live_source(source_url)
        plan = build_capture_plan(content_type, source.capabilities, payload.get("mode"))
    except (SourceProbeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return source, plan


@router.get("/api/live/capabilities")
def live_capabilities():
    _enabled()
    return {
        "audio": probe_host_audio(),
        "caption_ocr": {"provider": "tesseract", "available": TesseractCaptionOCR().available()},
    }


@router.post("/api/live/probe")
def live_probe(payload: dict = Body(...)):
    _enabled()
    source, plan = _probe(payload)
    return {"source": source.public_dict(), "capture_plan": plan.to_dict()}


@router.post("/api/live/sessions")
def start_live_session(payload: dict = Body(...)):
    _enabled()
    _recover_once()
    source, plan = _probe(payload)
    if source.source_kind != "hls" or plan.mode != "analyze_background" \
            or not plan.background_available:
        raise HTTPException(409, {
            "code": "background_unavailable",
            "message": "Background analysis is not available for this source. Keep the source window open to continue analysis.",
            "action": "open_source_and_analyze",
        })
    now = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    session_id = f"live-{now}-{secrets.token_hex(3)}"
    meeting_dir = MEETINGS / session_id
    try:
        return MANAGER.start_hls(
            source, meeting_dir, content_type=("media" if payload.get("content_type") == "live_event"
                                               else "meeting"),
            mode=plan.mode, dry_run=DRY_RUN)
    except LiveRuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/api/live/sessions")
def list_live_sessions():
    _enabled()
    _recover_once()
    return {"sessions": MANAGER.list()}


@router.get("/api/live/sessions/{session_id}")
def get_live_session(session_id: str):
    _enabled()
    _recover_once()
    worker = MANAGER.get(session_id)
    if worker is None:
        raise HTTPException(404, "Live session not found")
    return worker.status()


@router.get("/api/live/sessions/{session_id}/workspace")
def get_live_workspace(session_id: str):
    """Return bounded live review content without exposing signed source URLs."""
    _enabled()
    _recover_once()
    worker = MANAGER.get(session_id)
    if worker is None:
        raise HTTPException(404, "Live session not found")
    return worker.workspace()


@router.post("/api/live/sessions/{session_id}/stop")
def stop_live_session(session_id: str):
    _enabled()
    _recover_once()
    try:
        return MANAGER.stop(session_id)
    except LiveRuntimeError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/api/live/sessions/{session_id}/bookmark")
def bookmark_live(session_id: str):
    _enabled()
    worker = MANAGER.get(session_id)
    if worker is None or worker.recording_done.is_set():
        raise HTTPException(409, "No active recording")
    worker.bookmark_requested.set()
    return {"queued": True}


@router.get("/api/live/sessions/{session_id}/assets/{kind}/{asset_id}")
def live_asset(session_id: str, kind: str, asset_id: str):
    """Only serve manifest-listed local media, never remote playlist addresses."""
    _enabled()
    meeting = _mdir(session_id)
    try:
        if kind == "frame":
            from meeting_core.live.store import LiveSessionStore
            store = LiveSessionStore(meeting)
            entry = next(f for f in store.read_jsonl("frame-events.jsonl") if f["id"] == asset_id)
            root, relative = store.root, entry["file"]
        else:
            root = meeting / "live-recording"
            manifest = json.loads((root / "manifest.json").read_text())
            if kind == "segment":
                index = int(asset_id)
                if index < 0:
                    raise ValueError("negative index")
                relative = manifest["segments"][index]["file"]
            elif kind == "replay" and asset_id == "full":
                root, relative = meeting, manifest["replay"]
            else:
                raise ValueError("unsupported asset")
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError("invalid media path")
    except (OSError, ValueError, KeyError, IndexError, StopIteration):
        raise HTTPException(404, "Live media is not available")
    media_type = "video/mp4" if kind == "replay" else "video/mp2t" if kind == "segment" else "image/jpeg"
    return FileResponse(path, media_type=media_type,
                        filename=path.name if kind == "segment" else None)
