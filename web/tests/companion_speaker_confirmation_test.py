#!/usr/bin/env python3
"""Mobile speaker confirmation previews, then reuses bind/history services."""

import sys
from pathlib import Path

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "web"), str(ROOT / "bin")]
from companion_security import SessionGrant  # noqa: E402
from routers import companion  # noqa: E402


grant = SessionGrant("synthetic", "Phone", ("speaker_confirm",))
calls = []
companion._voice_in_item = lambda item, voice: calls.append(("scope", item, voice))
companion.speaker_routes.list_speakers = lambda: {"persons": [
    {"id": "p_1", "display_name": "Synthetic Person", "aliases": ["not exposed"]}]}
companion.speaker_routes.bind_in_meeting = lambda item, req: calls.append(
    ("bind", item, req.voice, req.name, req.create)) or {
        "ok": True, "name": req.name, "turns": 2, "how": "精确", "undo_available": True}
companion.speaker_routes.undo_speaker_operation = lambda item: calls.append(
    ("undo", item)) or {"ok": True, "operation": "bind"}

options = companion.speaker_correction_options("synthetic-item", "v_1", grant)
assert options["candidates"] == [{"id": "p_1", "name": "Synthetic Person"}]
assert options["provenance"] == "human_confirmed" and options["confirmation_required"]

payload = companion.SpeakerConfirmation(
    voice_id="v_1", person_name="Synthetic Person", confirm=False)
preview = companion.companion_speaker_confirmation("synthetic-item", payload, grant)
assert preview["state"] == "preview" and not any(row[0] == "bind" for row in calls)

confirmed = companion.companion_speaker_confirmation(
    "synthetic-item", payload.model_copy(update={"confirm": True}), grant)
assert confirmed["state"] == "confirmed" and confirmed["undo_available"]
assert ("bind", "synthetic-item", "v_1", "Synthetic Person", False) in calls
assert companion.companion_speaker_undo("synthetic-item", grant)["ok"]
assert ("undo", "synthetic-item") in calls

def missing(_item, _voice):
    raise HTTPException(404, "not in meeting")

companion._voice_in_item = missing
try:
    companion.companion_speaker_confirmation("other", payload, grant)
except HTTPException as exc:
    assert exc.status_code == 404
else:
    raise AssertionError("cross-meeting speaker cluster accepted")

print("companion speaker confirmation: preview, scoped bind, provenance and undo passed")
