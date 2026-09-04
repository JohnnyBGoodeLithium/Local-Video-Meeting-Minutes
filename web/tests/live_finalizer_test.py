#!/usr/bin/env python3
"""Live finalization reconciles draft inputs without rerunning ASR or speakers."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.finalizer import (LiveFinalizationError, mark_finalization_complete,
                                         prepare_finalization)
from meeting_core.live.fusion import fuse_text_signals
from meeting_core.live.models import TimedTextSignal
from meeting_core.live.store import LiveSessionStore


corrected = TimedTextSignal(
    id="corrected", start=0, end=2, text="校对后的字幕", speaker=None,
    text_source="native_subtitle", text_review_status="human_corrected",
    confidence_facets={"source": 1.0}, provisional=False,
)
automatic = TimedTextSignal(
    id="automatic", start=0, end=2, text="校对后的字母", speaker=None,
    text_source="native_transcript", text_review_status="automatic",
    confidence=0.99, confidence_facets={"source": 0.6, "recognition": 0.99},
)
turns, provenance = fuse_text_signals([automatic, corrected])
assert turns[0]["text"] == "校对后的字幕"
assert provenance[0]["selected"] == "corrected"

rolling = [TimedTextSignal(
    id=f"rolling-{index}", start=index * 6, end=index * 6 + 5,
    text=f"Segment {index}", speaker=None, text_source="local_asr",
) for index in range(4)]
bounded, _ = fuse_text_signals(rolling, max_turn_seconds=12, max_turn_chars=80)
assert len(bounded) == 2
assert bounded[0]["text"] == "Segment 0 Segment 1"


with tempfile.TemporaryDirectory(prefix="mm-live-finalizer-") as tmp:
    meeting = Path(tmp) / "meetings" / "synthetic-live"
    store = LiveSessionStore(meeting)
    store.initialize({"id": "synthetic"}, {"type": "replay"})
    store.append_signal(TimedTextSignal(
        id="asr-1", start=1, end=4, text="Synthetic line", speaker=None,
        text_source="local_asr", speaker_source="unknown"))
    store.append_signal(TimedTextSignal(
        id="native-1", start=1, end=4, text="Synthetic line.",
        speaker="Avery Example", text_source="native_transcript",
        speaker_source="platform_identity"))
    store.write_frame("frame-1", b"synthetic-image", at=2.0, reason="user_bookmark")
    store.save_checkpoint({"state": "ENDING", "media_time": 5, "text_signals": 2})

    plan = prepare_finalization(meeting, content_type="meeting")
    assert plan["state"] == "FINALIZING"
    assert plan["frames_reused"] == 1
    command_text = " ".join(part for command in plan["commands"] for part in command)
    assert "minutes_by_page.py" in command_text
    assert "transcribe.py" not in command_text
    assert "diarize.py" not in command_text
    assert "video_minutes.py" not in command_text
    turns = json.loads((meeting / "transcript.spk.json").read_text())
    assert turns == [{
        "speaker": "Avery Example", "start": 1.0, "end": 4.0,
        "text": "Synthetic line.",
    }]
    assert (meeting / "slides" / "live_page_001.jpg").read_bytes() == b"synthetic-image"
    assert json.loads((meeting / "meta.json").read_text())["live_context"] == "experimental"
    mark_finalization_complete(meeting)
    assert store.checkpoint()["state"] == "COMPLETE"

    try:
        prepare_finalization(meeting)
    except LiveFinalizationError:
        pass
    else:
        raise AssertionError("existing canonical transcript was overwritten")

print("live finalizer tests: OK")
