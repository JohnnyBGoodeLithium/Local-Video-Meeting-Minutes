"""Region-limited visual caption capture and temporal text merging."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Protocol

from .models import TimedTextSignal


@dataclass(frozen=True, slots=True)
class CaptionRegion:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.width, self.height)
        if any(value < 0 or value > 1 for value in values):
            raise ValueError("caption region coordinates must be within 0..1")
        if self.width <= 0 or self.height <= 0 or self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("caption region exceeds the frame")


class CaptionOCRProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def recognize(self, image: Path, *, language: str | None = None) -> str: ...


class TesseractCaptionOCR:
    name = "tesseract"

    def __init__(self, executable: str | None = None):
        self.executable = executable or shutil.which("tesseract")

    def available(self) -> bool:
        return bool(self.executable)

    def recognize(self, image: Path, *, language: str | None = None) -> str:
        if not self.executable:
            raise RuntimeError("Caption OCR unavailable")
        command = [self.executable, str(image), "stdout", "--psm", "6"]
        if language:
            command += ["-l", language]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise RuntimeError("Caption OCR unavailable")
        return " ".join(result.stdout.split())


class FakeCaptionOCR:
    name = "fake"

    def __init__(self, text: str = ""):
        self.text = text

    def available(self) -> bool:
        return True

    def recognize(self, image: Path, *, language: str | None = None) -> str:
        return self.text


class CaptionChangeDetector:
    """Cheap byte-sample change detector for an already cropped caption region."""

    def __init__(self, threshold: float = 0.02):
        if not 0 <= threshold <= 1:
            raise ValueError("caption change threshold must be within 0..1")
        self.threshold = threshold
        self.previous: bytes | None = None

    @staticmethod
    def _sample(payload: bytes, points: int = 512) -> bytes:
        if len(payload) <= points:
            return payload
        step = max(1, len(payload) // points)
        return payload[::step][:points]

    def changed(self, payload: bytes) -> bool:
        current = self._sample(payload)
        if self.previous is None:
            self.previous = current
            return True
        length = max(len(current), len(self.previous), 1)
        different = sum(a != b for a, b in zip(current, self.previous)) \
            + abs(len(current) - len(self.previous))
        self.previous = current
        return different / length >= self.threshold


def _overlap(left: str, right: str, minimum: int = 3) -> int:
    limit = min(len(left), len(right))
    for size in range(limit, minimum - 1, -1):
        if left[-size:] == right[:size]:
            return size
    return 0


class CaptionTemporalMerger:
    """Collapse caption growth/replacement into readable timed turns."""

    def __init__(self, *, min_display_seconds: float = 0.35):
        self.min_display_seconds = min_display_seconds
        self.current: dict | None = None
        self.counter = 0

    def observe(self, at: float, text: str, *, speaker: str | None = None) -> list[TimedTextSignal]:
        text = " ".join(text.split()).strip()
        if not text:
            return []
        if self.current is None:
            self.current = {"start": at, "end": at, "text": text, "speaker": speaker}
            return []
        current = self.current
        old = current["text"]
        current["end"] = at
        if text == old or old.startswith(text):
            return []
        if text.startswith(old):
            current["text"] = text
            current["speaker"] = speaker or current["speaker"]
            return []
        overlap = _overlap(old, text)
        if overlap:
            current["text"] = old + text[overlap:]
            current["speaker"] = speaker or current["speaker"]
            return []
        finished = self._finish(at)
        self.current = {"start": at, "end": at, "text": text, "speaker": speaker}
        return [finished] if finished else []

    def flush(self, at: float) -> list[TimedTextSignal]:
        if self.current is None:
            return []
        finished = self._finish(at, force=True)
        self.current = None
        return [finished] if finished else []

    def _finish(self, at: float, *, force: bool = False) -> TimedTextSignal | None:
        current = self.current
        if current is None:
            return None
        end = max(float(current["end"]), at)
        if not force and end - float(current["start"]) < self.min_display_seconds:
            return None
        self.counter += 1
        raw = f"caption\0{self.counter}\0{current['start']:.3f}\0{current['text']}"
        return TimedTextSignal(
            id=f"L{hashlib.sha256(raw.encode()).hexdigest()[:16]}",
            start=float(current["start"]), end=end, text=str(current["text"]),
            speaker=current["speaker"], text_source="ocr_caption",
            speaker_source="ocr_label" if current["speaker"] else "unknown",
            provisional=True, review_needed=True,
        )


@dataclass(slots=True)
class VisualCaptionCapture:
    region: CaptionRegion
    provider: CaptionOCRProvider
    fps: float = 2.0
    _last_sample: float | None = field(default=None, init=False, repr=False)
    _change: CaptionChangeDetector = field(default_factory=CaptionChangeDetector,
                                           init=False, repr=False)
    _merger: CaptionTemporalMerger = field(default_factory=CaptionTemporalMerger,
                                           init=False, repr=False)

    def __post_init__(self) -> None:
        if not 1 <= self.fps <= 5:
            raise ValueError("caption capture rate must be within 1..5 fps")
        self._last_sample = None

    def should_sample(self, at: float) -> bool:
        if self._last_sample is None or at - self._last_sample >= 1 / self.fps:
            self._last_sample = at
            return True
        return False

    def process_frame(self, image: Path, at: float, *, language: str | None = None) \
            -> list[TimedTextSignal]:
        """Crop the configured relative region and OCR only when it changes."""
        if not self.should_sample(at):
            return []
        if not self.provider.available():
            raise RuntimeError("Caption OCR unavailable")
        from PIL import Image

        with Image.open(image) as frame:
            width, height = frame.size
            box = (
                round(self.region.x * width), round(self.region.y * height),
                round((self.region.x + self.region.width) * width),
                round((self.region.y + self.region.height) * height),
            )
            crop = frame.crop(box).convert("RGB")
            if not self._change.changed(crop.tobytes()):
                return []
            with tempfile.NamedTemporaryFile(prefix="live-caption-", suffix=".png") as temp:
                crop.save(temp.name, "PNG")
                text = self.provider.recognize(Path(temp.name), language=language)
        speaker = None
        match = re.match(r"^([^:：]{1,40})\s*[:：]\s*(.+)$", text)
        if match:
            speaker, text = match.group(1).strip(), match.group(2).strip()
        return self._merger.observe(at, text, speaker=speaker)

    def flush(self, at: float) -> list[TimedTextSignal]:
        return self._merger.flush(at)
