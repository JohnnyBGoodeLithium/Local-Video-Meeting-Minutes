#!/usr/bin/env python3
"""Audio work always wins; degradation pauses lower-priority analysis first."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.backpressure import (AudioBackpressureController, AudioIntegrityError,
                                            PriorityWorkQueue)


queue = PriorityWorkQueue()
queue.put("vision", "frame")
queue.put("topic", "topic")
queue.put("audio_capture", "pcm")
queue.put("speaker", "speaker")
assert queue.get() == ("audio_capture", "pcm")
assert queue.get()[0] == "speaker"

controller = AudioBackpressureController(warn_seconds=5, critical_seconds=20)
assert controller.policy(0).level == 0
assert controller.policy(3).level == 1
assert controller.policy(6).level == 2 and controller.policy(6).vision_enabled is False
assert controller.policy(16).level == 3 and controller.policy(16).caption_ocr_enabled is False
assert controller.policy(21).level == 4 and controller.policy(21).topic_enabled is False
controller.assert_audio_integrity(0)
try:
    controller.assert_audio_integrity(1)
except AudioIntegrityError:
    pass
else:
    raise AssertionError("dropped primary audio did not stop live processing")

print("live backpressure tests: OK")
