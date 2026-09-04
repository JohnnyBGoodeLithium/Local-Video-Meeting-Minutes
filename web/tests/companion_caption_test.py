#!/usr/bin/env python3
"""Companion VTT remains protected, revision-aware, and translation-safe."""

from __future__ import annotations

import sys
import os
from pathlib import Path

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "web"), str(ROOT / "bin")]
from companion_security import SessionGrant  # noqa: E402
from routers import companion  # noqa: E402

grant = SessionGrant("session", "Synthetic", ("review",))
cues = [{"cue_id": "T000001-C01", "start": 1.0, "end": 3.0,
         "display_speaker": "Speaker A", "source_speaker_label": "Speaker A",
         "original_text": "Synthetic source", "translated_text": "虚构译文"}]
companion._meeting_identity = lambda _item: {"content_type": "meeting"}
companion._caption_payload = lambda _item, _target: (
    {"state": "ready", "source_revision": "rev-1"}, cues)
response = companion.companion_captions("synthetic", "bilingual", "zh-CN", "auto", "", grant)
assert response.media_type == "text/vtt" and "WEBVTT" in response.body.decode()
etag = response.headers["etag"]
cached = companion.companion_captions("synthetic", "bilingual", "zh-CN", "auto", etag, grant)
assert cached.status_code == 304

companion._caption_payload = lambda _item, _target: ({"state": "stale"}, cues)
try:
    companion.companion_captions("synthetic", "translation", "en", "auto", "", grant)
    raise AssertionError("stale translation caption accepted")
except HTTPException as exc:
    assert exc.status_code == 409

try:
    os.environ["MEETING_COMPANION"] = "1"
    companion._session("")
    raise AssertionError("caption session boundary bypassed")
except HTTPException as exc:
    assert exc.status_code == 401
print("companion captions: protected VTT, ETag and stale translation boundary passed")
