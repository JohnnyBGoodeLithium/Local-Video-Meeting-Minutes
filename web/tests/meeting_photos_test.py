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

    result = photos.import_photos(
        meeting, [(first, "Whiteboard.jpg"), (second, "Paper.png")],
        mode="capture_time", duration=3600,
        meeting_start_iso="2026-08-28T10:00:00+08:00")
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

    # 相同内容不产生第二份副本或新 ID。
    duplicate = root / "duplicate.webp"
    make_image(duplicate, (210, 220, 210))
    deduped = photos.import_photos(
        meeting, [(duplicate, "another-name.webp")], mode="current_time",
        anchor_seconds=900, duration=3600)
    assert deduped["imported"][0]["id"] == "F0003"
    assert len(deduped["photos"]) == 3

print("meeting photos: OK")
