#!/usr/bin/env python3
"""Selective vision triggers yield to audio backlog and preserve bookmarks."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.backpressure import AudioBackpressureController
from meeting_core.live.vision import (SelectiveVisionQueue, VisionTrigger, text_triggers,
                                      visual_lag_state)


triggers = text_triggers("Price is $499 with 16 GB memory and 20% less latency.", 12, "L1")
assert {item.reason for item in triggers} == {
    "number_or_percentage", "price_or_availability", "specification",
}
controller = AudioBackpressureController()
queue = SelectiveVisionQueue()
normal = controller.policy(0)
for trigger in triggers:
    assert queue.add(trigger, normal)
assert queue.add(VisionTrigger(12.5, "number_or_percentage", "L2"), normal) is False
assert queue.pop().reason in {"number_or_percentage", "price_or_availability", "specification"}

audio_busy = controller.policy(25)
assert queue.add(VisionTrigger(20, "scene_change"), audio_busy) is False
assert queue.add(VisionTrigger(20, "user_bookmark"), audio_busy) is True

assert visual_lag_state(12) == {"state": "catching_up", "lag_seconds": 12,
                                "acceptable": True}
assert visual_lag_state(31)["acceptable"] is False

print("live vision queue tests: OK")
