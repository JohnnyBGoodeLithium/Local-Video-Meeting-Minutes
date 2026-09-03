#!/usr/bin/env python3
"""Companion URL intake delegates to the existing validated import service."""

import sys
from pathlib import Path

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "web"), str(ROOT / "bin")]
from companion_security import SessionGrant  # noqa: E402
from routers import companion  # noqa: E402


grant = SessionGrant("synthetic", "Phone", ("send_url",))
seen = []


def fake_import(payload):
    seen.append(payload)
    if "private" in payload.url:
        raise HTTPException(400, "rejected by existing safe URL validation")
    return {"id": "synthetic-url", "status": "queued", "route": "media_url",
            "content_type": "media", "created": 1, "display_name": "Synthetic URL"}


companion.job_routes.import_media_url = fake_import
value = companion.companion_import_url(companion.LinkImport(url="https://example.test/video"), grant)
assert value["id"] == "synthetic-url" and seen[0].url == "https://example.test/video"
try:
    companion.companion_import_url(companion.LinkImport(url="https://private.invalid"), grant)
except HTTPException as exc:
    assert exc.status_code == 400
else:
    raise AssertionError("existing URL rejection was bypassed")

print("companion import URL: existing intake delegation passed")
