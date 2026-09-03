#!/usr/bin/env python3
"""Companion sessions cannot acquire capabilities they were not granted."""

import sys
from pathlib import Path

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(ROOT / "web"))

from companion_security import SessionGrant  # noqa: E402
from routers import companion  # noqa: E402


grant = SessionGrant("synthetic", "Synthetic phone", ("review",))
assert companion.require("review")(grant) == grant
try:
    companion.require("upload")(grant)
except HTTPException as exc:
    assert exc.status_code == 403
else:
    raise AssertionError("missing capability was accepted")

assert "admin" not in grant.capabilities
print("companion permissions: least privilege passed")
