#!/usr/bin/env python3
"""现场照片固化、EXIF 对齐和人工校正回归（全合成）。"""

import tempfile
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core import photos  # noqa: E402


def make_image(path: Path, color: tuple[int, int, int], captured: str | None = None) -> None:
    image = Image.new("RGB", (640, 360), color)
    exif = Image.Exif()
    if captured:
        exif[36867] = captured
    image.save(path, exif=exif)


with tempfile.TemporaryDirectory(prefix="meeting-photos-test-") as temp:
    root = Path(temp)
    meeting = root / "meetings" / "synthetic-meeting"
    meeting.mkdir(parents=True)
    first = root / "whiteboard.jpg"
    second = root / "paper.png"
    no_time = root / "untimed.webp"
    make_image(first, (240, 240, 230), "2026:08:28 10:05:00")
    make_image(second, (220, 230, 245), "2026:08:28 10:08:30")
    make_image(no_time, (210, 220, 210))

    # EXIF DateTimeOriginal and the browser's datetime-local value are both
    # wall-clock timestamps without a timezone; keep the synthetic fixture equivalent.
    result = photos.import_photos(
        meeting, [(first, "Whiteboard.jpg"), (second, "Paper.png")],
        mode="capture_time", duration=3600,
        meeting_start_iso="2026-08-28T10:00:00")
    assert [item["id"] for item in result["imported"]] == ["F0001", "F0002"]
    assert result["imported"][0]["alignment"] == {
        "seconds": 300.0, "state": "suggested",
        "method": "exif_meeting_start", "confidence": "high"}
    assert result["imported"][1]["alignment"]["seconds"] == 510.0
    first.unlink()
    second.unlink()
    assert (meeting / "photos/original/F0001.jpg").is_file()
    assert (meeting / "photos/review/F0001.jpg").is_file()

    untimed = photos.import_photos(
        meeting, [(no_time, "notes.webp")], mode="unlocated", duration=3600)
    assert untimed["imported"][0]["alignment"]["seconds"] is None
    assert untimed["imported"][0]["capture_time_source"] == "none"
    photos.set_alignment(meeting, "F0003", 725.5, duration=3600)
    projection = photos.project(meeting)
    assert [item["id"] for item in projection] == ["F0001", "F0002", "F0003"]
    assert projection[-1]["first"] == 725.5
    assert projection[-1]["kind"] == "photo"
    assert projection[-1]["asset_path"] == "photos/review/F0003.jpg"
    assert photos.analysis_revision(meeting) is None

    # 视觉分析状态和结果原子落到现场资料 sidecar；时间邻近只是上下文，不是决定证据。
    photos.set_analysis_state(meeting, ["F0001"], "queued")
    photos.set_analysis_state(meeting, ["F0001"], "analyzing")
    ready = photos.set_analysis_state(meeting, ["F0001"], "ready", results={
        "F0001": {"description": "## 标题\n规划白板\n## 可见内容\n- 两个工作流",
                  "model": "synthetic-vl"},
    })[0]
    assert ready["analysis_state"] == "ready" and ready["analysis_model"] == "synthetic-vl"
    materials = photos.prompt_materials(meeting, [
        {"start": 260, "end": 280}, {"start": 900, "end": 920},
    ])
    assert materials[0]["id"] == "F0001"
    assert materials[0]["nearby_turn_ids"] == ["T000001"]
    assert materials[0]["evidence_boundary"] == "visual_context_only_not_a_meeting_decision"
    ready_revision = photos.analysis_revision(meeting)
    assert ready_revision and len(ready_revision) == 16
    photos.set_title(meeting, "F0001", "Revised material title")
    assert photos.analysis_revision(meeting) != ready_revision

    # 相同内容不产生第二份副本或新 ID。
    duplicate = root / "duplicate.webp"
    make_image(duplicate, (210, 220, 210))
    deduped = photos.import_photos(
        meeting, [(duplicate, "another-name.webp")], mode="current_time",
        anchor_seconds=900, duration=3600)
    assert deduped["imported"][0]["id"] == "F0003"
    assert deduped["created_ids"] == []
    assert deduped["duplicate_ids"] == ["F0003"]
    assert deduped["results"][0]["duplicate"] is True
    assert len(deduped["photos"]) == 3

    # 改名只改变阅读标题，不触碰原始文件名和 hash。
    original_hash = photos.load(meeting)["photos"][0]["sha256"]
    renamed = photos.set_title(meeting, "F0001", "  Whiteboard   plan  ")
    assert renamed["title"] == "Whiteboard plan"
    assert renamed["original_name"] == "Whiteboard.jpg"
    assert renamed["sha256"] == original_hash

    # 删除同步清理 canonical 条目、受保护原图和阅读副本。
    removed = photos.delete_photo(meeting, "F0002")
    assert removed["deleted"]["id"] == "F0002"
    assert not (meeting / "photos/original/F0002.png").exists()
    assert not (meeting / "photos/review/F0002.jpg").exists()
    assert [item["id"] for item in photos.load(meeting)["photos"]] == ["F0001", "F0003"]

    # 被篡改为会议目录外路径的 sidecar 不得造成越界删除。
    outside = root / "must-survive.jpg"
    make_image(outside, (1, 2, 3))
    document = photos.load(meeting)
    document["photos"][0]["original_path"] = "../../must-survive.jpg"
    photos._atomic_json(meeting / "meeting.photos.json", document)
    try:
        photos.delete_photo(meeting, "F0001")
    except photos.PhotoError as exc:
        assert "路径不安全" in str(exc)
    else:
        raise AssertionError("unsafe photo path was accepted")
    assert outside.is_file()

with tempfile.TemporaryDirectory(prefix="meeting-photos-invalid-") as temp:
    root = Path(temp)
    meeting = root / "meeting"
    meeting.mkdir()
    invalid = root / "broken.jpg"
    invalid.write_bytes(b"not-an-image")
    try:
        photos.import_photos(meeting, [(invalid, "broken.jpg")])
    except photos.PhotoError as exc:
        assert "可读取的图片" in str(exc)
    else:
        raise AssertionError("invalid image was accepted")
    assert photos.load(meeting)["photos"] == []

print("meeting photos: OK")
