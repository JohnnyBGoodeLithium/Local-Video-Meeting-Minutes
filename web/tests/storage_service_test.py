#!/usr/bin/env python3
"""验证存储分类、白名单清理和符号链接边界。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "web"))
from storage_service import clean_meeting_cache, meeting_storage  # noqa: E402


with tempfile.TemporaryDirectory(prefix="storage-service-") as tmp:
    root = Path(tmp)
    meeting = root / "meetings" / "2099-01-01_synthetic"
    meeting.mkdir(parents=True)
    (meeting / "source_video.mp4").write_bytes(b"master")
    (meeting / "audio.wav").write_bytes(b"work-audio")
    (meeting / "transcript.spk.json").write_text("[]", encoding="utf-8")
    (meeting / "minutes.md").write_text("# 虚构会议", encoding="utf-8")
    (meeting / ".topic-map-work.json").write_text("{}", encoding="utf-8")
    (meeting / ".rag").mkdir()
    (meeting / ".rag" / "index.json").write_text("{}", encoding="utf-8")
    (meeting / "slides").mkdir()
    (meeting / "slides" / "full_0001.jpg").write_bytes(b"frame")
    (meeting / "page_desc.json").write_text('{"desc": {}}', encoding="utf-8")

    before = meeting_storage(meeting)
    assert before["original"] == {"bytes": 6, "files": 1, "protected": True}
    assert {group["id"] for group in before["cache"]["groups"]} == {
        "work_audio", "vl_frames", "rag", "topic_work"
    }

    result = clean_meeting_cache(meeting)
    assert result["removed_files"] == 4
    assert (meeting / "source_video.mp4").read_bytes() == b"master"
    assert (meeting / "transcript.spk.json").is_file()
    assert (meeting / "minutes.md").is_file()
    assert not (meeting / "audio.wav").exists()
    assert not (meeting / ".rag").exists()
    assert not (meeting / "slides" / "full_0001.jpg").exists()

    outside = root / "outside"
    outside.mkdir()
    external_frame = outside / "full_private.jpg"
    external_frame.write_bytes(b"must-survive")
    external_index = outside / "private-index.json"
    external_index.write_bytes(b"must-survive")
    (meeting / "slides").rmdir()
    (meeting / "slides").symlink_to(outside, target_is_directory=True)
    (meeting / ".rag").symlink_to(outside, target_is_directory=True)

    linked = meeting_storage(meeting)
    assert not linked["cache"]["reclaimable"]
    linked_result = clean_meeting_cache(meeting)
    assert linked_result["removed_files"] == 0
    assert external_frame.read_bytes() == b"must-survive"
    assert external_index.read_bytes() == b"must-survive"

print("Storage service: classification, cleanup allowlist, and symlink boundary OK")
