#!/usr/bin/env python3
"""验证会议媒体固化优先硬链接，且源文件删除后会议副本仍可用。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
from meeting_dir import materialize_source  # noqa: E402


with tempfile.TemporaryDirectory(prefix="media-materialize-") as tmp:
    root = Path(tmp)
    source = root / "inbox" / "synthetic.mp4"
    target = root / "meetings" / "synthetic" / "source_video.mp4"
    source.parent.mkdir()
    source.write_bytes(b"synthetic-media-not-a-real-recording")
    result = materialize_source(source, target)
    assert result == target.resolve()
    assert target.read_bytes() == b"synthetic-media-not-a-real-recording"
    assert source.stat().st_ino == target.stat().st_ino
    source.unlink()
    assert target.is_file() and target.read_bytes().startswith(b"synthetic-media")

print("Media materialization: hardlink survives source removal")
