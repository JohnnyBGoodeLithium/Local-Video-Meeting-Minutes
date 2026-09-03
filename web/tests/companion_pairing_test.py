#!/usr/bin/env python3
"""Companion pairing tokens are random, expiring, explicit, and single-use."""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web"))

from companion_security import CompanionStore


with tempfile.TemporaryDirectory(prefix="mm-companion-pair-") as tmp:
    store = CompanionStore(Path(tmp) / "auth.json")
    pairing = store.create_pairing(now=1000)
    assert len(pairing["token"]) >= 22 and len(pairing["short_code"]) == 6
    request = store.request_pairing(pairing["token"], "Synthetic phone", now=1001)
    assert store.pending(now=1002)[0]["request_id"] == request["request_id"]
    try:
        store.request_pairing(pairing["token"], "Second phone", now=1002)
    except ValueError as exc:
        assert str(exc) == "already_used"
    else:
        raise AssertionError("pairing token was reused")
    expired = store.create_pairing(now=2000)
    try:
        store.request_pairing(expired["token"], "Late phone", now=2301)
    except ValueError as exc:
        assert str(exc) == "invalid_or_expired"
    else:
        raise AssertionError("expired pairing token was accepted")

print("companion pairing: expiry and single-use passed")
