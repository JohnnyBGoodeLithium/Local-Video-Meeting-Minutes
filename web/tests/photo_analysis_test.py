#!/usr/bin/env python3
"""现场资料视觉分析作业：状态、结果和安全同步条件（全合成）。"""

import tempfile
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

import analyze_photos  # noqa: E402
from meeting_artifact import append_materials_section, build_prompt_context  # noqa: E402
from meeting_core import photos  # noqa: E402


with tempfile.TemporaryDirectory(prefix="photo-analysis-test-") as temp:
    root = Path(temp)
    meeting = root / "synthetic-meeting"
    meeting.mkdir()
    source = root / "whiteboard.jpg"
    Image.new("RGB", (640, 360), (242, 238, 220)).save(source)
    imported = photos.import_photos(meeting, [(source, "whiteboard.jpg")])
    photo_id = imported["created_ids"][0]

    original_model = analyze_photos._model_id
    original_chat = analyze_photos.chat_with_image
    analyze_photos._model_id = lambda _api: "synthetic-vl"
    analyze_photos.chat_with_image = lambda *_args, **_kwargs: (
        "## 标题\n规划白板\n## 可见内容\n- 流程 A 指向流程 B", {})
    try:
        completed, failed = analyze_photos.analyze(meeting, [photo_id], "synthetic://vl")
    finally:
        analyze_photos._model_id = original_model
        analyze_photos.chat_with_image = original_chat

    record = photos.load(meeting)["photos"][0]
    assert completed == 1 and failed == 0
    assert record["analysis_state"] == "ready"
    assert "规划白板" in record["description"]
    assert record["analysis_model"] == "synthetic-vl"
    assert analyze_photos._sync_command(meeting) is None

    turns = [{"speaker": "Alex", "start": 0, "end": 20,
              "text": "讨论虚构工作流。"}]
    materials = photos.prompt_materials(meeting, turns)
    context = build_prompt_context(turns, [], {}, [], materials=materials)
    assert context["materials"][0]["id"] == photo_id
    assert context["materials"][0]["evidence_boundary"] == \
        "visual_context_only_not_a_meeting_decision"
    minutes = append_materials_section("# 会议纪要\n", materials)
    assert "## 现场资料解读" in minutes and "不能单独证明会议已经作出决定" in minutes

    (meeting / "transcript.spk.json").write_text(
        __import__("json").dumps(turns, ensure_ascii=False), encoding="utf-8")
    (meeting / "transcript.txt").write_text("讨论虚构工作流。", encoding="utf-8")
    command = analyze_photos._sync_command(meeting)
    assert command and command[1].endswith("summarize.py") and "--skip-topic-map" in command

    failed_source = root / "paper.jpg"
    Image.new("RGB", (320, 240), (220, 230, 245)).save(failed_source)
    failed_id = photos.import_photos(meeting, [(failed_source, "paper.jpg")])["created_ids"][0]
    analyze_photos._model_id = lambda _api: "synthetic-vl"
    analyze_photos.chat_with_image = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("synthetic failure"))
    try:
        completed, failed = analyze_photos.analyze(meeting, [failed_id], "synthetic://vl")
    finally:
        analyze_photos._model_id = original_model
        analyze_photos.chat_with_image = original_chat
    failed_record = next(item for item in photos.load(meeting)["photos"]
                         if item["id"] == failed_id)
    assert completed == 0 and failed == 1 and failed_record["analysis_state"] == "failed"

print("photo analysis: state, local result, and safe sync gate passed")
