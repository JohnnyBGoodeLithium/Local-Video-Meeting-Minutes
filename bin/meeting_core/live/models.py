"""Typed, provider-neutral signals used while a source is still live."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


TEXT_SOURCES = {
    "native_transcript",
    "native_subtitle",
    "ocr_caption",
    "local_asr",
}

SPEAKER_SOURCES = {
    "platform_identity",
    "human_confirmed",
    "voice_profile",
    "local_diarization",
    "ocr_label",
    "unknown",
}


@dataclass(frozen=True, slots=True)
class TimedTextSignal:
    """One timed text observation plus explicit text/speaker provenance.

    Signals are live draft inputs, not canonical transcript turns.  They remain
    provisional until the finalizer reconciles them with the existing pipeline.
    """

    id: str
    start: float
    end: float
    text: str
    speaker: str | None
    text_source: str
    speaker_source: str = "unknown"
    language: str | None = None
    confidence: float | None = None
    provisional: bool = True
    review_needed: bool = False

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("signal id is required")
        if self.start < 0 or self.end < self.start:
            raise ValueError("signal timestamps are invalid")
        if not self.text.strip():
            raise ValueError("signal text is required")
        if self.text_source not in TEXT_SOURCES:
            raise ValueError(f"unsupported text source: {self.text_source}")
        if self.speaker_source not in SPEAKER_SOURCES:
            raise ValueError(f"unsupported speaker source: {self.speaker_source}")
        if self.speaker_source != "unknown" and not (self.speaker or "").strip():
            raise ValueError("known speaker provenance requires a speaker label")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TimedTextSignal":
        return cls(
            id=str(value["id"]),
            start=float(value["start"]),
            end=float(value["end"]),
            text=str(value["text"]),
            speaker=(str(value["speaker"]) if value.get("speaker") is not None else None),
            text_source=str(value["text_source"]),
            speaker_source=str(value.get("speaker_source") or "unknown"),
            language=(str(value["language"]) if value.get("language") else None),
            confidence=(float(value["confidence"])
                        if value.get("confidence") is not None else None),
            provisional=bool(value.get("provisional", True)),
            review_needed=bool(value.get("review_needed", False)),
        )
