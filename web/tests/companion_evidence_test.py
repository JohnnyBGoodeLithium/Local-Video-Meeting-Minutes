#!/usr/bin/env python3
"""Evidence lookup is meeting-scoped and media serving never accepts a path."""

import sys
from pathlib import Path

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "web"), str(ROOT / "bin")]
from companion_security import SessionGrant  # noqa: E402
from routers import companion  # noqa: E402


grant = SessionGrant("synthetic", "Phone", ("review",))
companion.companion_projection.item = lambda _mdir: {
    "evidence": [{"id": "C00001", "start": 2, "end": 4, "text": "Synthetic"}]}
companion._mdir = lambda slug: Path("/tmp/synthetic") if slug == "item-a" else (_ for _ in ()).throw(
    HTTPException(404, "meeting not found"))
value = companion.companion_evidence("item-a", "C00001", grant)
assert value["media_url"].endswith("/item-a/media/audio")
try:
    companion.companion_evidence("item-a", "OTHER", grant)
except HTTPException as exc:
    assert exc.status_code == 404
else:
    raise AssertionError("cross-meeting evidence id accepted")
try:
    companion.companion_media("../secret", "audio", grant)
except HTTPException as exc:
    assert exc.status_code == 404
else:
    raise AssertionError("path traversal accepted")

print("companion evidence: scoped lookup and path traversal boundary passed")
