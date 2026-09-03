#!/usr/bin/env python3
"""Teams cues keep their platform identity in the live layer."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.signals import teams_cue_signals


cues = [
    {"name": "Avery Example", "start": 1.0, "end": 3.0, "text": "Open the review."},
    {"name": "Example Room", "start": 3.0, "end": 6.0, "text": "Keep the room label."},
]
signals = teams_cue_signals(cues)
assert [item.speaker for item in signals] == ["Avery Example", "Example Room"]
assert all(item.text_source == "native_transcript" for item in signals)
assert all(item.speaker_source == "platform_identity" for item in signals)
assert all(item.provisional for item in signals)
assert len({item.id for item in signals}) == 2
assert teams_cue_signals(cues) == signals

print("teams live adapter tests: OK")
