"""Region-limited visual caption capture and temporal text merging."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import importlib.util
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


@dataclass(frozen=True, slots=True)
class CaptionDetection:
    region: CaptionRegion
    confidence: float

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("caption detection confidence must be within 0..1")


@dataclass(frozen=True, slots=True)
class CaptionOCRResult:
    text: str
    confidence: float | None = None


class CaptionRegionDetector(Protocol):
    name: str

    def available(self) -> bool: ...

    def detect(self, image: Path, *, language: str | None = None) \
            -> list[CaptionDetection]: ...


def _region_iou(left: CaptionRegion, right: CaptionRegion) -> float:
    x1, y1 = max(left.x, right.x), max(left.y, right.y)
    x2 = min(left.x + left.width, right.x + right.width)
    y2 = min(left.y + left.height, right.y + right.height)
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = left.width * left.height + right.width * right.height - intersection
    return intersection / union if union else 0.0


class CaptionRegionTracker:
    """Track a moving subtitle band without assuming bottom-screen placement."""

    def __init__(self, *, minimum_confidence: float = 0.45, maximum_misses: int = 2):
        self.minimum_confidence = minimum_confidence
        self.maximum_misses = maximum_misses
        self.region: CaptionRegion | None = None
        self.confidence: float | None = None
        self.misses = 0

    def update(self, detections: list[CaptionDetection]) -> CaptionRegion | None:
        candidates = [item for item in detections if item.confidence >= self.minimum_confidence]
        if candidates:
            if self.region is None:
                chosen = max(candidates, key=lambda item: item.confidence)
            else:
                chosen = max(candidates, key=lambda item: (
                    0.65 * _region_iou(self.region, item.region) + 0.35 * item.confidence
                ))
            self.region, self.confidence, self.misses = chosen.region, chosen.confidence, 0
        elif self.region is not None:
            self.misses += 1
            if self.misses > self.maximum_misses:
                self.region, self.confidence = None, None
        return self.region


class FakeCaptionRegionDetector:
    name = "fake"

    def __init__(self, detections: list[CaptionDetection]):
        self.detections = detections

    def available(self) -> bool:
        return True

    def detect(self, image: Path, *, language: str | None = None) \
            -> list[CaptionDetection]:
        return list(self.detections)


class PaddleOCRv6CaptionOCR:
    """Local-only PP-OCRv6 adapter; model directories must already exist."""

    name = "pp-ocrv6"

    def __init__(self, detection_model_dir: Path, recognition_model_dir: Path,
                 *, device: str = "cpu"):
        self.detection_model_dir = Path(detection_model_dir)
        self.recognition_model_dir = Path(recognition_model_dir)
        self.device = device
        self._pipeline = None

    def available(self) -> bool:
        return (importlib.util.find_spec("paddleocr") is not None
                and self.detection_model_dir.is_dir()
                and self.recognition_model_dir.is_dir())

    def _engine(self):
        if not self.available():
            raise RuntimeError("PP-OCRv6 caption models unavailable")
        if self._pipeline is None:
            from paddleocr import PaddleOCR
            self._pipeline = PaddleOCR(
                ocr_version="PP-OCRv6",
                text_detection_model_dir=str(self.detection_model_dir),
                text_recognition_model_dir=str(self.recognition_model_dir),
                device=self.device,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        return self._pipeline

    @staticmethod
    def _payload(result) -> dict:
        value = getattr(result, "json", result)
        if callable(value):
            value = value()
        if isinstance(value, dict) and isinstance(value.get("res"), dict):
            value = value["res"]
        return value if isinstance(value, dict) else {}

    def _predict(self, image: Path) -> list[dict]:
        return [self._payload(item) for item in self._engine().predict(input=str(image))]

    def recognize(self, image: Path, *, language: str | None = None) -> CaptionOCRResult:
        texts, scores = [], []
        for payload in self._predict(image):
            texts.extend(str(item).strip() for item in payload.get("rec_texts", []) if str(item).strip())
            scores.extend(float(item) for item in payload.get("rec_scores", []))
        confidence = sum(scores) / len(scores) if scores else None
        return CaptionOCRResult(" ".join(texts), confidence)

    def detect(self, image: Path, *, language: str | None = None) -> list[CaptionDetection]:
        from PIL import Image

        with Image.open(image) as frame:
            width, height = frame.size
        detections = []
        for payload in self._predict(image):
            polygons = payload.get("dt_polys", [])
            scores = payload.get("dt_scores") or payload.get("rec_scores") or []
            for index, polygon in enumerate(polygons):
                points = list(polygon)
                if not points:
                    continue
                xs, ys = [float(point[0]) for point in points], [float(point[1]) for point in points]
                x1, x2 = max(0.0, min(xs) / width), min(1.0, max(xs) / width)
                y1, y2 = max(0.0, min(ys) / height), min(1.0, max(ys) / height)
                if x2 <= x1 or y2 <= y1:
                    continue
                score = float(scores[index]) if index < len(scores) else 0.5
                detections.append(CaptionDetection(
                    CaptionRegion(x1, y1, x2 - x1, y2 - y1), score))
        return detections


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

    def observe(self, at: float, text: str, *, speaker: str | None = None,
                confidence_facets: dict[str, float] | None = None) -> list[TimedTextSignal]:
        text = " ".join(text.split()).strip()
        if not text:
            return []
        if self.current is None:
            self.current = {"start": at, "end": at, "text": text, "speaker": speaker,
                            "confidence_facets": confidence_facets or {}}
            return []
        current = self.current
        old = current["text"]
        current["end"] = at
        if text == old or old.startswith(text):
            return []
        if text.startswith(old):
            current["text"] = text
            current["speaker"] = speaker or current["speaker"]
            current["confidence_facets"].update(confidence_facets or {})
            return []
        overlap = _overlap(old, text)
        if overlap:
            current["text"] = old + text[overlap:]
            current["speaker"] = speaker or current["speaker"]
            current["confidence_facets"].update(confidence_facets or {})
            return []
        finished = self._finish(at)
        self.current = {"start": at, "end": at, "text": text, "speaker": speaker,
                        "confidence_facets": confidence_facets or {}}
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
            confidence=(current["confidence_facets"].get("recognition")),
            confidence_facets=dict(current["confidence_facets"]),
            text_review_status="automatic",
            provisional=True, review_needed=True,
        )


@dataclass(slots=True)
class VisualCaptionCapture:
    region: CaptionRegion | None
    provider: CaptionOCRProvider
    fps: float = 2.0
    detector: CaptionRegionDetector | None = None
    redetect_seconds: float = 2.0
    _last_sample: float | None = field(default=None, init=False, repr=False)
    _change: CaptionChangeDetector = field(default_factory=CaptionChangeDetector,
                                           init=False, repr=False)
    _merger: CaptionTemporalMerger = field(default_factory=CaptionTemporalMerger,
                                           init=False, repr=False)
    _tracker: CaptionRegionTracker = field(default_factory=CaptionRegionTracker,
                                           init=False, repr=False)
    _last_detection: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not 1 <= self.fps <= 5:
            raise ValueError("caption capture rate must be within 1..5 fps")
        if self.region is None and self.detector is None:
            raise ValueError("adaptive caption capture requires a region detector")
        if self.redetect_seconds <= 0:
            raise ValueError("caption re-detection interval must be positive")
        self._last_sample = None

    def should_sample(self, at: float) -> bool:
        if self._last_sample is None or at - self._last_sample >= 1 / self.fps:
            self._last_sample = at
            return True
        return False

    def process_frame(self, image: Path, at: float, *, language: str | None = None) \
            -> list[TimedTextSignal]:
        """Detect/track a caption region, then OCR only when its pixels change."""
        if not self.should_sample(at):
            return []
        if not self.provider.available():
            raise RuntimeError("Caption OCR unavailable")
        from PIL import Image

        region = self.region
        if self.detector is not None and (
                self._last_detection is None or at - self._last_detection >= self.redetect_seconds
                or self._tracker.region is None):
            if not self.detector.available():
                raise RuntimeError("Caption region detector unavailable")
            region = self._tracker.update(self.detector.detect(image, language=language))
            self._last_detection = at
        elif self.detector is not None:
            region = self._tracker.region
        if region is None:
            return []

        with Image.open(image) as frame:
            width, height = frame.size
            box = (
                round(region.x * width), round(region.y * height),
                round((region.x + region.width) * width),
                round((region.y + region.height) * height),
            )
            crop = frame.crop(box).convert("RGB")
            if not self._change.changed(crop.tobytes()):
                return []
            with tempfile.NamedTemporaryFile(prefix="live-caption-", suffix=".png") as temp:
                crop.save(temp.name, "PNG")
                result = self.provider.recognize(Path(temp.name), language=language)
        if isinstance(result, CaptionOCRResult):
            text, recognition_confidence = result.text, result.confidence
        else:
            text, recognition_confidence = result, None
        speaker = None
        match = re.match(r"^([^:：]{1,40})\s*[:：]\s*(.+)$", text)
        if match:
            speaker, text = match.group(1).strip(), match.group(2).strip()
        facets = {"source": 0.55, "temporal": 0.5}
        if recognition_confidence is not None:
            facets["recognition"] = recognition_confidence
        if self.detector is not None and self._tracker.confidence is not None:
            facets["region"] = self._tracker.confidence
        return self._merger.observe(at, text, speaker=speaker, confidence_facets=facets)

    def flush(self, at: float) -> list[TimedTextSignal]:
        return self._merger.flush(at)
