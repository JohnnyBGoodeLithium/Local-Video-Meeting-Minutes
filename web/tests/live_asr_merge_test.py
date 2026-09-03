#!/usr/bin/env python3
"""Rolling ASR overlap dedup and provisional/stable behavior."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.asr import (ASRChunk, ASRSegment, ChunkedNearLiveASR,
                                   NearLiveTranscript, RollingChunkPlanner, merge_overlap_text)


assert merge_overlap_text("we should revisit", "revisit the margin") == \
       "we should revisit the margin"
assert merge_overlap_text("确认边界", "边界之后继续") == "确认边界之后继续"

planner = RollingChunkPlanner(8, 2)
assert planner.windows(20) == [(0.0, 8.0), (6.0, 14.0), (12.0, 20)]

transcript = NearLiveTranscript()
transcript.ingest([ASRSegment(0, 8, "we should revisit")], stable_before=0)
segments = transcript.ingest(
    [ASRSegment(6, 14, "revisit the margin assumption")], stable_before=6)
assert len(segments) == 1
assert segments[0].text == "we should revisit the margin assumption"
assert segments[0].provisional is True
segments = transcript.ingest([ASRSegment(15, 18, "next item")], stable_before=14)
assert segments[0].provisional is False and segments[1].provisional is True
signals = transcript.signals(language="en")
assert signals[0].text_source == "local_asr" and signals[0].provisional is False
assert signals[1].review_needed is True

class FakeProvider:
    name = "fake"

    def transcribe_chunk(self, chunk):
        return [ASRSegment(chunk.start, chunk.end, "synthetic words")]

runner = ChunkedNearLiveASR(FakeProvider())
assert runner.process(ASRChunk(0, 5, b"\0\0" * 50))[0].text == "synthetic words"

print("live ASR merge tests: OK")
