"""Freeze a live draft, reconcile it, and hand off to existing canonical stages."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys

from .fusion import fuse_text_signals
from .state import LiveSourceState
from .store import LiveSessionStore


class LiveFinalizationError(RuntimeError):
    """A live draft cannot safely enter the canonical pipeline."""


def _atomic_json(path: Path, value) -> None:
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _materialize_frames(store: LiveSessionStore) -> int:
    events = store.read_jsonl("frame-events.jsonl")
    if not events:
        return 0
    slides = store.meeting_dir / "slides"
    slides.mkdir(exist_ok=True)
    pages = []
    for number, event in enumerate(events, 1):
        relative = PurePosixPath(str(event.get("file") or ""))
        if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("frames",):
            raise LiveFinalizationError("unsafe live frame reference")
        source = store.root.joinpath(*relative.parts)
        if not source.is_file():
            raise LiveFinalizationError("live frame cache is incomplete")
        name = f"live_page_{number:03d}{source.suffix.lower()}"
        shutil.copyfile(source, slides / name)
        at = float(event.get("at") or 0)
        pages.append({
            "kind": "slide", "page": number, "first": at, "captured": at,
            "image": name, "ranges": [[at, at + 1.0]],
        })
    _atomic_json(store.meeting_dir / "slides.json", pages)
    return len(pages)


def prepare_finalization(meeting_dir: Path, *, content_type: str = "meeting",
                         source_media: Path | None = None) -> dict:
    """Publish reconciled canonical text and return existing-stage commands.

    The returned commands intentionally contain no transcribe.py, diarize.py,
    teams_minutes.py, or video_minutes.py invocation.
    """
    if content_type not in {"meeting", "media"}:
        raise LiveFinalizationError("unsupported final content type")
    store = LiveSessionStore(meeting_dir)
    checkpoint = store.checkpoint()
    if checkpoint.get("state") not in {"ENDING", "LIVE", "STALLED"}:
        raise LiveFinalizationError("live session is not ready to finalize")
    target = store.meeting_dir / "transcript.spk.json"
    if target.exists():
        raise LiveFinalizationError("canonical transcript already exists")
    store.save_checkpoint({**checkpoint, "state": LiveSourceState.FINALIZING.value,
                           "input_frozen": True})
    turns, provenance = fuse_text_signals(store.signals())
    if not turns:
        raise LiveFinalizationError("live draft contains no timed text")
    _atomic_json(store.root / "reconciled-transcript.json", {
        "schema": "meeting-live-reconciliation/v1", "turns": turns,
        "provenance": provenance,
    })
    _atomic_json(target, turns)
    (store.meeting_dir / "transcript.txt").write_text(
        "\n".join(item["text"] for item in turns) + "\n", encoding="utf-8")
    (store.meeting_dir / "transcript.spk.md").write_text(
        "# Live Context 逐字稿\n\n" + "\n".join(
            f"[{int(item['start']) // 60:02d}:{int(item['start']) % 60:02d}] "
            f"**{item['speaker']}**: {item['text']}" for item in turns) + "\n",
        encoding="utf-8",
    )
    meta_path = store.meeting_dir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        meta = {}
    meta.update({"content_type": content_type, "live_context": "experimental"})
    _atomic_json(meta_path, meta)

    frame_count = _materialize_frames(store)
    python = str(Path(os.environ.get("MEETING_PYTHON", sys.executable)))
    root = Path(__file__).resolve().parents[3]
    commands = []
    if frame_count:
        commands.append([python, str(root / "bin" / "minutes_by_page.py"),
                         str(store.meeting_dir), "--publish"])
    elif source_media is not None and source_media.is_file() \
            and source_media.suffix.lower() not in {".wav", ".mp3", ".m4a", ".flac"}:
        commands.append([python, str(root / "bin" / "slide_pages.py"), str(source_media),
                         "--out", str(store.meeting_dir / "slides")])
        commands.append([python, str(root / "bin" / "minutes_by_page.py"),
                         str(store.meeting_dir), "--video", str(source_media), "--publish"])
    else:
        commands.append([python, str(root / "bin" / "summarize.py"),
                         str(store.meeting_dir / "transcript.txt"), "--spk", str(target),
                         "--max-tokens", "8192"])
    plan = {
        "state": LiveSourceState.FINALIZING.value,
        "turns": len(turns), "frames_reused": frame_count,
        "commands": commands, "reuses_asr": True, "reuses_speaker": True,
        "canonical_handoff": True,
    }
    _atomic_json(store.root / "finalization.json", plan)
    return plan


def mark_finalization_complete(meeting_dir: Path) -> None:
    store = LiveSessionStore(meeting_dir)
    checkpoint = store.checkpoint()
    if checkpoint.get("state") != LiveSourceState.FINALIZING.value:
        raise LiveFinalizationError("live session is not finalizing")
    store.save_checkpoint({**checkpoint, "state": LiveSourceState.COMPLETE.value})
