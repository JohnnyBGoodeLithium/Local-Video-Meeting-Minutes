#!/usr/bin/env python3
"""Companion device sessions persist only token hashes and revoke immediately."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web"))

from companion_security import CompanionStore, DEFAULT_CAPABILITIES


with tempfile.TemporaryDirectory(prefix="mm-companion-session-") as tmp:
    path = Path(tmp) / "auth.json"
    store = CompanionStore(path)
    pairing = store.create_pairing(now=1000)
    request = store.request_pairing(pairing["token"], "Synthetic phone", now=1001)
    store.decide(request["request_id"], True, now=1002)
    state, claim = store.pairing_status(
        request["request_id"], pairing["token"], claim=True, now=1003)
    assert state == "approved" and claim
    grant = store.authenticate(claim["token"], now=1004)
    assert grant and grant.capabilities == DEFAULT_CAPABILITIES
    raw = path.read_text(encoding="utf-8")
    assert claim["token"] not in raw and pairing["token"] not in raw
    assert json.loads(raw)["sessions"][0]["token_hash"]
    assert store.revoke(grant.id)
    assert store.authenticate(claim["token"], now=1005) is None

print("companion session: hashed persistence and revoke passed")
