#!/usr/bin/env python3
"""Replay-as-live preserves source timestamps and resumes without duplicates."""

import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.replay import replay
from meeting_core.live.store import LiveSessionStore


class Clock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        assert seconds >= 0
        self.value += seconds


with tempfile.TemporaryDirectory(prefix="mm-live-replay-") as tmp:
    root = Path(tmp)
    wav = root / "synthetic.wav"
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(100)
        handle.writeframes(b"\0\0" * 1000)  # ten seconds; no real meeting audio
    vtt = root / "synthetic.vtt"
    vtt.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nFirst synthetic cue.\n\n"
        "00:00:07.000 --> 00:00:08.000\nSecond synthetic cue.\n",
        encoding="utf-8",
    )
    meeting = root / "meetings" / "replay"
    clock = Clock()
    result = replay(wav, meeting, speed=10, subtitle=vtt, no_vl=True,
                    sleep=clock.sleep, monotonic=clock.monotonic)
    assert result["state"] == "ENDING" and result["media_time"] == 10.0
    assert 0.89 <= clock.value <= 1.01
    signals = LiveSessionStore(meeting).signals()
    assert [item.start for item in signals] == [1.0, 7.0]
    assert all(item.provisional for item in signals)

    second_clock = Clock()
    replay(wav, meeting, speed=100, subtitle=vtt,
           sleep=second_clock.sleep, monotonic=second_clock.monotonic)
    assert len(LiveSessionStore(meeting).signals()) == 2

print("live replay tests: OK")
