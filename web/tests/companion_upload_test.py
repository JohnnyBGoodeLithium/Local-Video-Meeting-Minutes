#!/usr/bin/env python3
"""Companion upload is streamed, bounded, sanitized and delegated."""

import asyncio
import sys
import tempfile
from pathlib import Path

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "web"), str(ROOT / "bin")]
from routers import jobs  # noqa: E402


class FakeUpload:
    def __init__(self, name, chunks):
        self.filename = name
        self.chunks = list(chunks)

    async def read(self, _size):
        return self.chunks.pop(0) if self.chunks else b""


class Executor:
    def submit(self, *_args):
        return None


with tempfile.TemporaryDirectory(prefix="companion-upload-") as tmp:
    root = Path(tmp)
    jobs.INBOX = root / "inbox"
    jobs.DATA_ROOT = root
    jobs.EXEC = Executor()
    jobs._predict_meeting = lambda *_args, **_kwargs: "synthetic-meeting"
    jobs._new_job = lambda kind, **kwargs: {"id": "synthetic-upload", "kind": kind,
                                            "status": "queued", "created": 1, **kwargs}
    try:
        asyncio.run(jobs.upload_with_limit([FakeUpload("../../escape.wav", [b"1234"])],
                                           max_bytes=3))
    except HTTPException as exc:
        assert exc.status_code == 413
    else:
        raise AssertionError("oversized upload accepted")
    assert not any(path.is_dir() for path in jobs.INBOX.glob("*"))

    value = asyncio.run(jobs.upload_with_limit(
        [FakeUpload("../../synthetic.wav", [b"12", b"34"])], max_bytes=10))
    assert value["files"] == ["synthetic.wav"]
    assert all(path.resolve().is_relative_to(jobs.INBOX.resolve())
               for path in jobs.INBOX.rglob("*") if path.is_file())

print("companion upload: stream limit and filename boundary passed")
