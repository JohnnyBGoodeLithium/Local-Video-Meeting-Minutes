#!/usr/bin/env python3
"""Starlette FileResponse provides real byte ranges for approved Companion media."""

from __future__ import annotations

import sys
import tempfile
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "web"), str(ROOT / "bin")]
from companion_security import SessionGrant  # noqa: E402
from routers import companion  # noqa: E402

grant = SessionGrant("synthetic", "Phone", ("review",))


async def request(response, range_header: str = ""):
    messages = []
    headers = [(b"range", range_header.encode())] if range_header else []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await response({"type": "http", "method": "GET", "path": "/media",
                    "headers": headers}, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages
                    if message["type"] == "http.response.body")
    response_headers = {key.decode(): value.decode() for key, value in start["headers"]}
    return start["status"], response_headers, body


with tempfile.TemporaryDirectory(prefix="companion-range-") as tmp:
    root = Path(tmp)
    approved = root / "synthetic"
    approved.mkdir()
    media = approved / "video.mp4"
    media.write_bytes(bytes(range(64)))
    companion._mdir = lambda item: approved if item == "synthetic" else (_ for _ in ()).throw(
        ValueError("outside approved meeting"))
    companion._video_path = lambda mdir: media if mdir == approved else None
    companion._audio_path = lambda _mdir: None
    whole = asyncio.run(request(companion.companion_media("synthetic", "video", grant)))
    assert whole[0] == 200 and whole[2] == bytes(range(64))
    middle = asyncio.run(request(companion.companion_media("synthetic", "video", grant),
                                 "bytes=20-29"))
    assert middle[0] == 206 and middle[2] == bytes(range(20, 30))
    assert middle[1]["content-range"] == "bytes 20-29/64"
    assert middle[1]["accept-ranges"] == "bytes"
    tail = asyncio.run(request(companion.companion_media("synthetic", "video", grant),
                               "bytes=-8"))
    assert tail[0] == 206 and tail[2] == bytes(range(56, 64))
print("companion media range: initial, middle seek, tail seek and 206 headers passed")
