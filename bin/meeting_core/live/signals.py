"""Adapters from existing transcript/subtitle shapes to live signals."""

from __future__ import annotations

import hashlib
from typing import Iterable

from .models import TimedTextSignal
from .vtt import WebVTTCue


def _signal_id(namespace: str, index: int, start: float, end: float, text: str) -> str:
    raw = f"{namespace}\0{index}\0{start:.3f}\0{end:.3f}\0{text}".encode("utf-8")
    return f"L{hashlib.sha256(raw).hexdigest()[:16]}"


def teams_cue_signals(cues: Iterable[dict], *, namespace: str = "teams",
                      provisional: bool = True,
                      human_corrected: bool = False) -> list[TimedTextSignal]:
    """Preserve Teams platform identity while adapting existing parser output."""
    signals = []
    for index, cue in enumerate(cues):
        text = str(cue.get("text") or "").strip()
        speaker = str(cue.get("name") or "").strip() or None
        start, end = float(cue["start"]), float(cue["end"])
        signals.append(TimedTextSignal(
            id=_signal_id(namespace, index, start, end, text),
            start=start,
            end=end,
            text=text,
            speaker=speaker,
            text_source="native_transcript",
            speaker_source="platform_identity" if speaker else "unknown",
            text_review_status=("human_corrected" if human_corrected
                                else "platform_provided"),
            confidence_facets={"source": 1.0 if human_corrected else 0.9},
            provisional=provisional,
        ))
    return signals


def generic_subtitle_signals(cues: Iterable[WebVTTCue], *, namespace: str = "subtitle",
                             language: str | None = None,
                             provisional: bool = True,
                             human_corrected: bool = False) -> list[TimedTextSignal]:
    """Adapt generic subtitles without treating visual labels as known identity."""
    signals = []
    for index, cue in enumerate(cues):
        signals.append(TimedTextSignal(
            id=_signal_id(namespace, index, cue.start, cue.end, cue.text),
            start=cue.start,
            end=cue.end,
            text=cue.text,
            speaker=None,
            text_source="native_subtitle",
            speaker_source="unknown",
            language=language,
            text_review_status=("human_corrected" if human_corrected
                                else "platform_provided"),
            confidence_facets={"source": 1.0 if human_corrected else 0.9},
            provisional=provisional,
        ))
    return signals
