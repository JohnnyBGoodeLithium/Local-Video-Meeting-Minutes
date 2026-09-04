#!/usr/bin/env python3
"""Cross-meeting display rename snapshots restore only the latest safe state."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web"))
import person_rename_history as history  # noqa: E402


with tempfile.TemporaryDirectory(prefix="person-rename-history-") as tmp:
    root = Path(tmp)
    bank = root / "bank"
    meetings = root / "meetings"
    meeting = meetings / "synthetic"
    bank.mkdir()
    meeting.mkdir(parents=True)
    (bank / "bank.json").write_text('{"name":"Luca Yang"}', encoding="utf-8")
    before = [{"voice": "v_1", "speaker": "Luca Yang", "text": "Synthetic"}]
    (meeting / "transcript.spk.json").write_text(json.dumps(before), encoding="utf-8")
    (meeting / "transcript.spk.md").write_text("Luca Yang: Synthetic", encoding="utf-8")

    operation = history.begin(bank, meetings, "p_1", ["synthetic"])
    (bank / "bank.json").write_text('{"name":"Luca"}', encoding="utf-8")
    after = [{"voice": "v_1", "speaker": "Luca", "text": "Synthetic"}]
    (meeting / "transcript.spk.json").write_text(json.dumps(after), encoding="utf-8")
    (meeting / "transcript.spk.md").write_text("Luca: Synthetic", encoding="utf-8")
    history.complete(operation, bank, meetings)

    available = history.latest(bank, meetings, "p_1")
    assert available and available[0] == operation
    history.rollback(operation, bank, meetings, require_current=True)
    assert json.loads((bank / "bank.json").read_text())["name"] == "Luca Yang"
    assert json.loads((meeting / "transcript.spk.json").read_text()) == before
    assert history.latest(bank, meetings, "p_1") is None

print("person rename history: cross-meeting revision guard and undo passed")
