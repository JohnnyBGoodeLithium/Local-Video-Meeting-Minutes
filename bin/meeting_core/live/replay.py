"""Replay finite local media on its original timeline as a live source."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time
import wave

from teams_transcript import parse_transcript

from .signals import generic_subtitle_signals, teams_cue_signals
from .store import LiveSessionStore
from .vtt import parse_webvtt


class ReplayError(RuntimeError):
    """Replay input is missing or cannot expose a media duration."""


def media_duration(path: Path) -> float:
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as handle:
                return handle.getnframes() / float(handle.getframerate())
        except (OSError, wave.Error) as exc:
            raise ReplayError("WAV input cannot be read") from exc
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        duration = float(result.stdout.strip())
    except ValueError as exc:
        raise ReplayError("media duration is unavailable") from exc
    if result.returncode or duration <= 0:
        raise ReplayError("media duration is unavailable")
    return duration


def _signals(transcript: Path | None, subtitle: Path | None):
    if transcript and subtitle:
        raise ReplayError("choose transcript or subtitle, not both")
    if transcript:
        return teams_cue_signals(parse_transcript(transcript), namespace=transcript.name)
    if subtitle:
        return generic_subtitle_signals(parse_webvtt(subtitle), namespace=subtitle.name)
    return []


def replay(media: Path, meeting_dir: Path, *, speed: float = 1.0,
           transcript: Path | None = None, subtitle: Path | None = None,
           no_vl: bool = False, num_speakers: int | None = None,
           sleep=time.sleep, monotonic=time.monotonic) -> dict:
    """Run a deterministic replay while preserving source media timestamps."""
    media = Path(media)
    if not media.is_file():
        raise ReplayError("media input does not exist")
    if speed <= 0:
        raise ReplayError("replay speed must be positive")
    duration = media_duration(media)
    signals = _signals(transcript, subtitle)
    store = LiveSessionStore(meeting_dir)
    store.initialize(
        {"kind": "replay", "provisional": True},
        {"type": "local_replay", "media_name": media.name, "duration": duration,
         "speed": speed, "no_vl": bool(no_vl), "num_speakers": num_speakers},
    )
    checkpoint = store.checkpoint()
    resume_at = float(checkpoint.get("media_time") or 0)
    store.save_checkpoint({"state": "LIVE", "media_time": resume_at,
                           "text_signals": len(store.signals())})
    started = monotonic()
    appended = 0
    for signal in signals:
        if signal.end <= resume_at:
            continue
        target = max(0.0, signal.start - resume_at) / speed
        delay = target - (monotonic() - started)
        if delay > 0:
            sleep(delay)
        appended += int(store.append_signal(signal))
        store.save_checkpoint({"state": "LIVE", "media_time": signal.end,
                               "text_signals": len(store.signals())})
    remaining = max(0.0, duration - float(store.checkpoint().get("media_time") or 0)) / speed
    if remaining > 0:
        sleep(remaining)
    final = {
        "state": "ENDING",
        "media_time": duration,
        "text_signals": len(store.signals()),
        "end_signal": "replay_eof",
    }
    store.save_checkpoint(final)
    store.append("metrics.jsonl", {
        "duration": round(duration, 3),
        "wall_seconds": round(monotonic() - started, 3),
        "text_signals_appended": appended,
    })
    return {**final, "live_dir": str(store.root)}
