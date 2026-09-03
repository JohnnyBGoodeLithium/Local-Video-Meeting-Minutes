"""Selective live visual evidence scheduling; never blocks primary audio."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import heapq
import re

from .backpressure import DegradationPolicy


TRIGGER_PRIORITY = {
    "user_bookmark": 0,
    "number_or_percentage": 1,
    "price_or_availability": 1,
    "specification": 1,
    "topic_change": 2,
    "scene_change": 3,
    "periodic_safety": 4,
}

NUMBER = re.compile(r"(?:\b\d+(?:\.\d+)?\s*%|[$€£¥]\s*\d|\b\d+(?:\.\d+)?\s*(?:GB|TB|GHz|ms|fps)\b)", re.I)
AVAILABILITY = re.compile(r"\b(?:available|availability|ships?|launch(?:es|ing)?|price|pricing)\b|(?:售价|价格|上市|发售|可用)", re.I)
SPECIFICATION = re.compile(r"\b(?:spec(?:ification)?|memory|battery|latency|resolution|throughput)\b|(?:规格|内存|续航|延迟|分辨率|吞吐)", re.I)


@dataclass(frozen=True, slots=True)
class VisionTrigger:
    at: float
    reason: str
    source_signal_id: str | None = None

    def __post_init__(self) -> None:
        if self.at < 0 or self.reason not in TRIGGER_PRIORITY:
            raise ValueError("invalid vision trigger")

    def to_dict(self) -> dict:
        return asdict(self)


def text_triggers(text: str, at: float, source_signal_id: str | None = None) -> list[VisionTrigger]:
    reasons = []
    if NUMBER.search(text):
        reasons.append("number_or_percentage")
    if AVAILABILITY.search(text):
        reasons.append("price_or_availability")
    if SPECIFICATION.search(text):
        reasons.append("specification")
    return [VisionTrigger(at, reason, source_signal_id) for reason in reasons]


class SelectiveVisionQueue:
    def __init__(self, *, dedupe_seconds: float = 2.0):
        self.dedupe_seconds = dedupe_seconds
        self._items: list[tuple[int, float, int, VisionTrigger]] = []
        self._seen: list[VisionTrigger] = []
        self._sequence = 0

    def add(self, trigger: VisionTrigger, policy: DegradationPolicy) -> bool:
        if not policy.vision_enabled and trigger.reason != "user_bookmark":
            return False
        if any(item.reason == trigger.reason and abs(item.at - trigger.at) <= self.dedupe_seconds
               for item in self._seen):
            return False
        heapq.heappush(self._items, (TRIGGER_PRIORITY[trigger.reason], trigger.at,
                                    self._sequence, trigger))
        self._sequence += 1
        self._seen.append(trigger)
        return True

    def pop(self) -> VisionTrigger:
        if not self._items:
            raise IndexError("vision queue is empty")
        return heapq.heappop(self._items)[-1]

    def __len__(self) -> int:
        return len(self._items)


def visual_lag_state(lag_seconds: float) -> dict:
    return {
        "state": "catching_up" if lag_seconds > 5 else "current",
        "lag_seconds": round(max(0.0, lag_seconds), 1),
        "acceptable": lag_seconds <= 30,
    }
