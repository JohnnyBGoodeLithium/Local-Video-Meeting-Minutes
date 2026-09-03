#!/usr/bin/env python3
"""Live benchmark output contains metadata only."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.metrics import LiveMetrics, benchmark_summary


metrics = LiveMetrics()
metrics.record("asr_lag_seconds", 2.5)
metrics.record("dropped_audio_chunks", 0)
assert metrics.latest() == {"asr_lag_seconds": 2.5, "dropped_audio_chunks": 0.0}
for unsafe in ("transcript", "speaker_name", "meeting_title", "source_url", "token"):
    try:
        metrics.record(unsafe, 1)
    except ValueError:
        pass
    else:
        raise AssertionError(f"unsafe metric accepted: {unsafe}")

summary = benchmark_summary(
    duration=100, wall_seconds=25, asr_lag=[2, 3, 4], speaker_lag=[5, 6],
    caption_lag=[1], vl_lag=[10, 30], audio_backlog=[0, 2, 1],
    dropped_audio_chunks=0, peak_memory_bytes=1024,
)
assert summary["rtf"] == 0.25
assert summary["asr_lag_p50"] == 3
assert summary["max_audio_backlog"] == 2
assert summary["dropped_audio_chunks"] == 0
assert set(summary).isdisjoint({"transcript", "speaker", "url", "token"})

print("live metrics tests: OK")
