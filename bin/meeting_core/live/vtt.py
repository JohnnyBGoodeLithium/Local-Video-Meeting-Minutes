"""Dependency-free WebVTT parsing shared by live and Teams adapters."""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from pathlib import Path
import re


_TIMING = re.compile(
    r"(?P<start>(?:\d{1,3}:)?\d{1,2}:\d{2}[.,]\d{3})\s*-->\s*"
    r"(?P<end>(?:\d{1,3}:)?\d{1,2}:\d{2}[.,]\d{3})(?:[ \t]+[^\n\r]*)?"
)
_VOICE = re.compile(r"<v(?:\.[^\s>]+)?\s+([^>]+)>(.*?)</v>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")


class WebVTTError(ValueError):
    """The supplied WebVTT did not contain usable timed cues."""


@dataclass(frozen=True, slots=True)
class WebVTTCue:
    start: float
    end: float
    text: str
    speaker: str | None = None


def timestamp_seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    raise WebVTTError("unrecognized WebVTT timestamp")


def _plain(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(_TAG.sub("", value))).strip()


def parse_webvtt_text(raw: str) -> list[WebVTTCue]:
    """Parse complete WebVTT text without assuming a specific platform."""
    raw = raw.lstrip("\ufeff")
    cues: list[WebVTTCue] = []
    for block in re.split(r"\r?\n\s*\r?\n", raw):
        if block.lstrip().startswith(("NOTE", "STYLE", "REGION")):
            continue
        timing = _TIMING.search(block)
        if not timing:
            continue
        body = block[timing.end():]
        voice = _VOICE.search(body)
        speaker = _plain(voice.group(1)) if voice else None
        text = _plain(voice.group(2) if voice else body)
        if not text:
            continue
        start = timestamp_seconds(timing.group("start"))
        end = timestamp_seconds(timing.group("end"))
        if end <= start:
            continue
        cues.append(WebVTTCue(start=start, end=end, text=text, speaker=speaker))
    if not cues:
        raise WebVTTError("WebVTT contains no usable timed cues")
    return cues


def parse_webvtt(path: Path) -> list[WebVTTCue]:
    return parse_webvtt_text(path.read_text(encoding="utf-8", errors="replace"))
