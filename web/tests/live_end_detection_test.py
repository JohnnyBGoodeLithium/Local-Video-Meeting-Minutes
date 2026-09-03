#!/usr/bin/env python3
"""Live end detection distinguishes gaps, recovery, ENDLIST, and LIVE-to-VOD."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.end_detection import LiveEndDetector
from meeting_core.live.state import LiveSourceState


detector = LiveEndDetector(stall_seconds=90, grace_seconds=30)
assert detector.connected(0).state == LiveSourceState.LIVE
assert detector.observe(89).state == LiveSourceState.LIVE
assert detector.observe(90).state == LiveSourceState.STALLED
assert detector.observe(100, progressed=True).state == LiveSourceState.LIVE
assert detector.observe(190).state == LiveSourceState.STALLED
assert detector.observe(220).state == LiveSourceState.ENDING
assert detector.observe(249).finalize is False
assert detector.observe(250).finalize is True

endlist = LiveEndDetector()
endlist.connected(0)
decision = endlist.observe(10, endlist=True)
assert decision.state == LiveSourceState.ENDING and decision.finalize is True
assert decision.reason == "hls_endlist"

vod = LiveEndDetector()
vod.connected(0)
decision = vod.observe(30, live_to_vod=True)
assert decision.finalize is True and decision.live_to_vod is True

recover = LiveEndDetector(stall_seconds=2, grace_seconds=2)
recover.connected(0)
recover.observe(2)
recover.observe(4)
assert recover.observe(4.5, progressed=True).state == LiveSourceState.LIVE

print("live end detection tests: OK")
