#!/usr/bin/env python3
"""验证逻辑页、连续视觉片段与语义章节的分层投影（全虚构数据）。"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
import meeting_structure  # noqa: E402


turns = [
    {"speaker": "Alex", "start": 1, "end": 3, "text": "合成开场"},
    {"speaker": "Bo", "start": 7, "end": 9, "text": "合成章节一"},
    {"speaker": "Alex", "start": 12, "end": 14, "text": "合成章节二"},
    {"speaker": "Bo", "start": 17, "end": 19, "text": "返回第一页"},
]
timeline = [
    {"kind": "slide", "page": 1, "first": 0, "image": "page1.png",
     "ranges": [[0, 5], [15, 20]]},
    {"kind": "slide", "page": 2, "first": 5, "image": "page2.png",
     "ranges": [[5, 15]]},
]
minutes = """# 会议纪要

## 议题板块

- 方案介绍（第1页，00:00 起）：介绍虚构方案。
- 方案讨论（第2页，00:10 起）：讨论虚构方案。

## 分页详情
"""
claims = [
    {"id": "C00001", "kind": "decision", "status": "confirmed",
     "turn_indexes": [1], "page_ids": ["P0002"]},
    {"id": "C00002", "kind": "action", "status": "open",
     "turn_indexes": [2], "page_ids": ["P0002"]},
]
descriptions = {1: "## 标题\n第一页标题", 2: "## 标题\n第二页标题"}
structure = meeting_structure.build_structure(
    minutes, turns, timeline, descriptions, {"claims": claims}, duration=20)

assert structure["schema"] == "meeting-structure/v1"
assert structure["chapter_source"] == "minutes_topic"
assert len(structure["segments"]) == 3
assert [segment["page"] for segment in structure["segments"]] == [1, 2, 1]
assert len(structure["chapters"]) == 2
assert structure["chapters"][0]["decision_claim_ids"] == ["C00001"]
assert structure["chapters"][1]["action_claim_ids"] == ["C00002"]
page_one = next(visual for visual in structure["visuals"] if visual["id"] == "P0001")
assert len(page_one["segment_ids"]) == 2
assert page_one["title"] == "第一页标题"

fallback = meeting_structure.build_structure("# 旧纪要", turns, timeline, descriptions, {}, duration=20)
assert fallback["chapter_source"] == "visual_segments"
assert len(fallback["chapters"]) == 3

print("Meeting structure: segments, chapters, and repeated pages passed")
