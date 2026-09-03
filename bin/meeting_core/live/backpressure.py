"""Priority and degradation policy that always protects primary audio."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from typing import Any


PRIORITY = {
    "audio_capture": 0,
    "text_asr": 1,
    "speaker": 1,
    "topic": 2,
    "caption_ocr": 3,
    "vision": 4,
    "final_heavy": 5,
}


class AudioIntegrityError(RuntimeError):
    """Primary audio loss is a hard stop, never a normal degradation."""


@dataclass(frozen=True, slots=True)
class DegradationPolicy:
    level: int
    vision_enabled: bool
    vision_frequency: float
    caption_ocr_enabled: bool
    topic_enabled: bool


class AudioBackpressureController:
    def __init__(self, *, warn_seconds: float = 5, critical_seconds: float = 20):
        if warn_seconds <= 0 or critical_seconds <= warn_seconds:
            raise ValueError("invalid audio backlog thresholds")
        self.warn_seconds = warn_seconds
        self.critical_seconds = critical_seconds

    def policy(self, backlog_seconds: float) -> DegradationPolicy:
        if backlog_seconds < self.warn_seconds / 2:
            return DegradationPolicy(0, True, 1.0, True, True)
        if backlog_seconds < self.warn_seconds:
            return DegradationPolicy(1, True, 0.5, True, True)
        if backlog_seconds < self.critical_seconds * 0.75:
            return DegradationPolicy(2, False, 0.0, True, True)
        if backlog_seconds < self.critical_seconds:
            return DegradationPolicy(3, False, 0.0, False, True)
        return DegradationPolicy(4, False, 0.0, False, False)

    @staticmethod
    def assert_audio_integrity(dropped_audio_chunks: int) -> None:
        if dropped_audio_chunks:
            raise AudioIntegrityError("primary audio chunks were dropped")


class PriorityWorkQueue:
    def __init__(self):
        self._items: list[tuple[int, int, str, Any]] = []
        self._sequence = 0

    def put(self, kind: str, value: Any) -> None:
        if kind not in PRIORITY:
            raise ValueError("unsupported live work kind")
        heapq.heappush(self._items, (PRIORITY[kind], self._sequence, kind, value))
        self._sequence += 1

    def get(self) -> tuple[str, Any]:
        if not self._items:
            raise IndexError("live work queue is empty")
        _priority, _sequence, kind, value = heapq.heappop(self._items)
        return kind, value

    def __len__(self) -> int:
        return len(self._items)
