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

- <think>不要展示这段推理</think>方案介绍（第1页，00:00 起）：介绍虚构方案。
- 方案讨论（第2页，00:10 起）：讨论虚构方案。

## 分页详情
"""
claims = [
    {"id": "C00001", "kind": "decision", "status": "confirmed",
     "turn_indexes": [1], "page_ids": ["P0002"]},
    {"id": "C00002", "kind": "action", "status": "open",
     "turn_indexes": [2], "page_ids": ["P0002"]},
]
descriptions = {
    1: "<think>hidden reasoning</think>\n## 标题\n第一页标题\n## 页面角色\ncontent\n## 信息价值\nhigh：包含架构图。",
    2: "## 标题\n第二页标题\n## 页面角色\ntransition\n## 信息价值\nlow：只有过渡标题。",
}
structure = meeting_structure.build_structure(
    minutes, turns, timeline, descriptions, {"claims": claims}, duration=20)

assert structure["schema"] == "meeting-structure/v2"
assert structure["chapter_source"] == "minutes_topic"
assert len(structure["segments"]) == 3
assert [segment["page"] for segment in structure["segments"]] == [1, 2, 1]
assert len(structure["chapters"]) == 2
assert structure["chapters"][0]["decision_claim_ids"] == ["C00001"]
assert structure["chapters"][1]["action_claim_ids"] == ["C00002"]
assert structure["chapters"][0]["title"] == "方案介绍"
page_one = next(visual for visual in structure["visuals"] if visual["id"] == "P0001")
assert len(page_one["segment_ids"]) == 2
assert page_one["title"] == "第一页标题"
assert page_one["information_value"] == "high"
assert page_one["value_source"] == "vl"
assert "<think>" not in page_one["description"]
assert "页面角色" not in page_one["display_description"]
assert "信息价值" not in page_one["display_description"]
page_two = next(visual for visual in structure["visuals"] if visual["id"] == "P0002")
assert page_two["information_value"] == "low"
assert meeting_structure.clean_model_text("reasoning</think>## 标题\n答案") == "## 标题\n答案"
assert meeting_structure.clean_model_text("before<think>unfinished") == "before"

fallback = meeting_structure.build_structure("# 旧纪要", turns, timeline, descriptions, {}, duration=20)
assert fallback["chapter_source"] == "visual_segments"
assert len(fallback["chapters"]) == 2
assert all(chapter["title"] != "第二页标题" for chapter in fallback["chapters"])

pending = meeting_structure.build_structure(
    "# 处理中", turns, [timeline[0]], {}, {}, duration=20)["visuals"][0]
assert pending["information_value"] == "unknown"
assert pending["value_label"] == "待解析"
assert pending["analysis_state"] == "pending"
assert not pending["needs_reprocess"]

empty_cached = meeting_structure.build_structure(
    "# 旧缓存", turns, [timeline[0]], {1: "<think>只有推理，没有正文"}, {},
    duration=20)["visuals"][0]
assert empty_cached["information_value"] == "unknown"
assert empty_cached["analysis_state"] == "failed"
assert empty_cached["needs_reprocess"]

short_but_valid = meeting_structure._visual_value("简短但有效的页面说明。", "业务更新")
assert short_but_valid["information_value"] == "medium"

# VL 把答案包进 \boxed{…} 或转义 Markdown（\## 标题）时，标题/角色/价值都要还原
boxed = "\\boxed{\n\\## 标题\n合成战略标题\n\\## 页面角色\ncontent\n}\n"
assert meeting_structure.visual_title(boxed, 7) == "合成战略标题"
assert meeting_structure._visual_role(cleaned := meeting_structure.clean_model_text(boxed),
                                      "合成战略标题") == "content"
assert "\\" not in cleaned and "boxed" not in cleaned

# JSON 片段形态的标题与字段（boxed 清洗拆掉外层花括号后尤其常见）
jsonish = '"标题": "合成界面截图",\n "页面角色": "meeting_ui",\n "信息价值": "low",\n "页面内容": "合成正文"'
assert meeting_structure.visual_title(jsonish, 1) == "合成界面截图"
json_value = meeting_structure._visual_value(jsonish, "合成界面截图")
assert json_value["content_role"] == "meeting_ui"
assert json_value["information_value"] == "low"
assert json_value["value_source"] == "vl"

print("Meeting structure: segments, chapters, and repeated pages passed")
