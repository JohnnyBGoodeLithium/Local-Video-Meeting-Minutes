#!/usr/bin/env python3
"""Display rename and simple binding stay deterministic and model-free."""

from __future__ import annotations

import inspect
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "web"), str(ROOT / "bin")]
from routers import speakers  # noqa: E402
from person_display import display_person, display_revision  # noqa: E402


model_calls = {name: 0 for name in
               ("asr", "diarization", "vl", "minutes", "topic", "translation")}
effects = []


@contextmanager
def transaction(*_args, **_kwargs):
    yield


with tempfile.TemporaryDirectory(prefix="identity-no-rerun-") as tmp:
    mdir = Path(tmp) / "synthetic"
    mdir.mkdir()
    speakers._mdir = lambda _slug: mdir
    speakers.sh.transaction = transaction
    speakers._bind_voice = lambda *_args, **_kwargs: ("Luca", "exact", "P001")
    speakers._rename_voice_in_meeting = lambda *_args: effects.append("transcript") or 12
    speakers.sc.lock_turns = lambda *_args, **_kwargs: effects.append("locks")
    speakers._read_json = lambda *_args, **_kwargs: [
        {"voice": "v_1", "speaker": "Speaker A", "text": "Synthetic"}]
    speakers._refresh_evidence = lambda *_args: effects.append("evidence")
    result = speakers.bind_in_meeting(
        "synthetic", speakers.BindReq(voice="v_1", name="Luca", create=False))
    assert result["turns"] == 12 and effects == ["transcript", "locks", "evidence"]

for operation in (speakers.bind_in_meeting, speakers.update_person):
    source = inspect.getsource(operation)
    assert not any(token in source for token in
                   ("assistant_service", "transcribe", "diariz", "describe_pages",
                    "generate_topic_map", "translate_")), source

assert all(value == 0 for value in model_calls.values())
assert display_person({"display_name": "Luca"}, session_label="Speaker A") == "Luca"
assert display_person(None, native_name="Native Name", session_label="Speaker A") == "Native Name"
assert display_person(None, session_label="Speaker A") == "Speaker A"
assert display_revision([{"person_id": "P001", "display_name": "Luca",
                          "voice_ids": ["v_1"]}])
print("identity no-rerun: display rename/simple binding model counters all zero")
