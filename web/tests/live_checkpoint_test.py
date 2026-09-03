#!/usr/bin/env python3
"""Live runtime checkpoints are atomic and JSONL recovery is append-safe."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.models import TimedTextSignal
from meeting_core.live.store import LIVE_SCHEMA, LiveSessionStore, LiveStoreError


with tempfile.TemporaryDirectory(prefix="mm-live-checkpoint-") as tmp:
    meeting = Path(tmp) / "meetings" / "synthetic-live"
    store = LiveSessionStore(meeting)
    store.initialize({"id": "synthetic"}, {"type": "replay"})
    assert store.root.name == ".live"
    assert store.checkpoint()["state"] == "CONNECTING"
    assert json.loads((store.root / "session.json").read_text())["schema"] == LIVE_SCHEMA

    signal = TimedTextSignal(
        id="L1", start=1, end=2, text="Synthetic cue.", speaker=None,
        text_source="native_subtitle",
    )
    assert store.append_signal(signal) is True
    assert store.append_signal(signal) is False
    with (store.root / "text-signals.jsonl").open("ab") as handle:
        handle.write(b'{"id":"torn"')
    assert [item.id for item in store.signals()] == ["L1"]

    store.save_checkpoint({"state": "LIVE", "media_time": 2.0, "text_signals": 1})
    checkpoint = store.checkpoint()
    assert checkpoint["media_time"] == 2.0 and checkpoint["state"] == "LIVE"
    assert not list(store.root.glob("*.tmp-*"))

    try:
        store.append("../escape.jsonl", {})
    except LiveStoreError:
        pass
    else:
        raise AssertionError("unsafe live path accepted")

print("live checkpoint tests: OK")
