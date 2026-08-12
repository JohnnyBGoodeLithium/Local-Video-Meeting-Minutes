#!/usr/bin/env python3
"""验证会议媒体固化为独立母版，删除或修改源文件都不影响母版。"""

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
    assert source.stat().st_ino != target.stat().st_ino
    source.write_bytes(b"source-was-modified")
    assert target.read_bytes() == b"synthetic-media-not-a-real-recording"
    source.unlink()
    assert target.is_file() and target.read_bytes().startswith(b"synthetic-media")

print("Media materialization: independent CoW/copy survives source mutation and removal")
