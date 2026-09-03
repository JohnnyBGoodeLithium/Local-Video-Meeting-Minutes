#!/usr/bin/env python3
"""Live signal validation and provenance tests (fictional data only)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.models import TimedTextSignal


signal = TimedTextSignal(
    id="L-example",
    start=12.5,
    end=15.0,
    text="The fictional review is open.",
    speaker="Avery Example",
    text_source="native_transcript",
    speaker_source="platform_identity",
    language="en",
)
assert signal.provisional is True

corrected = TimedTextSignal(
    id="corrected", start=0, end=1, text="Human checked", speaker=None,
    text_source="native_subtitle", text_review_status="human_corrected",
    confidence_facets={"source": 1.0, "recognition": 0.99}, provisional=False,
)
assert TimedTextSignal.from_dict(corrected.to_dict()) == corrected
assert TimedTextSignal.from_dict(signal.to_dict()) == signal

for changes in (
    {"id": ""},
    {"start": 16.0},
    {"text": ""},
    {"text_source": "model_guess"},
    {"speaker": None, "speaker_source": "platform_identity"},
    {"confidence": 1.2},
):
    values = signal.to_dict()
    values.update(changes)
    try:
        TimedTextSignal.from_dict(values)
    except ValueError:
        pass
    else:
        raise AssertionError(f"invalid signal accepted: {changes}")

print("live signal tests: OK")
