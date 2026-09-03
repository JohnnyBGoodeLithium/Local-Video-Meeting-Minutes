#!/usr/bin/env python3
"""Growing/flickering OCR captions collapse into stable provisional turns."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.captions import CaptionTemporalMerger


merger = CaptionTemporalMerger()
assert merger.observe(1.0, "We should") == []
assert merger.observe(2.0, "We should revisit") == []
assert merger.observe(3.0, "We should revisit the margin") == []
assert merger.observe(4.0, "We should revisit the margin assumption") == []
assert merger.observe(4.1, "We should revisit the margin") == []  # short replacement flicker
finished = merger.observe(5.0, "Next topic begins")
assert len(finished) == 1
assert finished[0].text == "We should revisit the margin assumption"
assert finished[0].start == 1.0 and finished[0].end == 5.0
assert finished[0].provisional and finished[0].review_needed

assert merger.observe(6.0, "topic begins with evidence") == []
tail = merger.flush(7.0)
assert tail[0].text == "Next topic begins with evidence"

speaker = CaptionTemporalMerger()
speaker.observe(10.0, "Review starts", speaker="Avery")
cue = speaker.flush(11.0)[0]
assert cue.speaker == "Avery" and cue.speaker_source == "ocr_label"

print("caption merge tests: OK")
