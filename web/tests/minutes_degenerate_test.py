#!/usr/bin/env python3
"""总体纪要输出退化防护：重复循环检测、重试与确定性清理。"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))

from meeting_core.llm import Completion  # noqa: E402
from meeting_core.minutes_overview import (  # noqa: E402
    _clean_degenerate, _complete_with_guard, _is_degenerate)


HEALTHY = ("## 总体摘要\n- **主旨**：合成会议，讨论产品计划 [依据](#mm-C00001)。\n\n"
           "### 待办事项\n\n| 事项 | 负责人 | 期限 | 状态 |\n| --- | --- | --- | --- |\n"
           "| 合成待办 [依据](#mm-A00001) | 合成负责人 | 待确认 | open |\n\n"
           "### 风险/待确认\n- 无\n\n"
           "## 议题板块\n- 合成议题（第1–2页，00:00 起）：合成说明 [依据](#mm-C00002)。")

LOOP_LINE = ("由于片段5中未提供具体编号给到这一结论，仅提供了讨论内容；"
             "根据规则结论需有编号，若无法提供则不能标为已确认，需归为工作对齐。")
DEGENERATE = ("## 总体摘要\n- **主旨**：合成会议。\n- **关键结论**：\n"
              f"- 已确认：合成结论。\n{LOOP_LINE}\n" * 6
              + "最终决定：" + LOOP_LINE + "\n" + "实际执行：" + LOOP_LINE + "\n"
              + "修正：" + LOOP_LINE + "\n(自我修正：仍为循环。)\n")

# 检测器本身
assert not _is_degenerate(HEALTHY)
assert _is_degenerate(DEGENERATE)
# 正常纪要里少量“（注：”不算退化
note_heavy = HEALTHY + "\n- 附注（注：合成标注）。\n- 再注（注：合成标注2）。"
assert not _is_degenerate(note_heavy)

# 清理：重复长行只留首行，自我修正链整行删除
cleaned = _clean_degenerate(DEGENERATE)
assert cleaned.count(LOOP_LINE) == 1
assert "最终决定" not in cleaned and "实际执行" not in cleaned
assert "## 总体摘要" in cleaned


class FakeClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def complete(self, prompt, **kwargs):
        self.calls.append(kwargs)
        content = self.outputs.pop(0)
        return Completion(content=content, usage={}, elapsed=0.01)


# 首次健康：不重试
client = FakeClient([HEALTHY])
result = _complete_with_guard(client, "prompt", max_tokens=100,
                              required=("### 待办事项",))
assert result.content == HEALTHY and len(client.calls) == 1

# 首次退化：用 repeat_penalty 重试，第二次健康则直接采用
client = FakeClient([DEGENERATE, HEALTHY])
result = _complete_with_guard(client, "prompt", max_tokens=100,
                              required=("### 待办事项",))
assert result.content == HEALTHY and len(client.calls) == 2
assert client.calls[1].get("repeat_penalty") == 1.2

# 两次都退化：确定性清理后继续走，不失败
client = FakeClient([DEGENERATE, DEGENERATE])
result = _complete_with_guard(client, "prompt", max_tokens=100)
assert result.content.count(LOOP_LINE) == 1
assert "最终决定" not in result.content

# 健康但缺必需章节（被截断）：也触发重试
truncated = "## 总体摘要\n- **主旨**：合成会议。\n- **关键结论**：无。"
client = FakeClient([truncated, HEALTHY])
result = _complete_with_guard(client, "prompt", max_tokens=100,
                              required=("### 待办事项",))
assert result.content == HEALTHY and len(client.calls) == 2

print("Minutes degenerate guard: detect / retry / clean all pass")

# ---- 待办章节证据标记合规 ----
from meeting_core.minutes_overview import (  # noqa: E402
    _splice_todo_section, _todo_compliant, generate)

MARK = "<!-- mm:evidence kind=action status=confirmed confidence=high turns=T000101 -->"
GOOD_TODO = ("### 待办事项\n\n| 事项 | 负责人 | 期限 | 状态 |\n| --- | --- | --- | --- |\n"
             f"| 合成待办 {MARK} | 合成负责人 | 待确认 | open |\n")
assert _todo_compliant("## 总体摘要\nx\n" + GOOD_TODO + "\n### 风险/待确认\n- 无")
assert _todo_compliant("### 待办事项\n未形成明确待办\n")
assert not _todo_compliant("### 待办事项\n\n| 事项 | 负责人 | 期限 | 状态 |\n"
                           "| --- | --- | --- | --- |\n| 无标记待办 | 某人 | 待确认 | open |\n")
assert not _todo_compliant("## 总体摘要\n没有待办章节")

spliced = _splice_todo_section(
    "## 总体摘要\n主旨\n### 待办事项\n\n旧表\n\n### 风险/待确认\n- 无\n", GOOD_TODO)
assert GOOD_TODO.strip() in spliced and "旧表" not in spliced and "### 风险/待确认" in spliced

# 端到端：reduce 待办不合规 → 触发定点修复并拼接
class RepairClient:
    def __init__(self):
        self.kinds = []

    def complete(self, prompt, **kwargs):
        if "overview-chunk/v1" in prompt:
            self.kinds.append("map")
            return Completion(content="- 合成事实 T000101", usage={}, elapsed=0.01)
        if "上一份纪要草稿的待办章节" in prompt:
            self.kinds.append("repair")
            return Completion(content="```markdown\n" + GOOD_TODO + "```",
                              usage={}, elapsed=0.01)
        self.kinds.append("reduce")
        return Completion(
            content=("## 总体摘要\n- **主旨**：合成。\n\n"
                     "### 待办事项\n\n| 事项 | 负责人 | 期限 | 状态 |\n| --- | --- | --- | --- |\n"
                     "| 无标记待办 | 某人 | 待确认 | open |\n\n"
                     "### 风险/待确认\n- 无\n\n## 议题板块\n- 合成议题：合成。"),
            usage={}, elapsed=0.01)

turns = [{"id": "T000101", "index": 0, "start": 0.0, "end": 4.0,
          "speaker": "合成说话人", "voice_id": None, "person_id": None,
          "page_id": "P0001", "text": "合成待办来源。" * 3}]
context = {"schema": "meeting-minutes-prompt/v1", "speaker_profiles": [],
           "pages": [], "turns": turns}
rc = RepairClient()
out = generate(context, {"version": "synthetic/v1"}, "只使用合成证据。", client=rc)
assert "reduce" in rc.kinds and "repair" in rc.kinds, rc.kinds
assert _todo_compliant(out.content) and MARK in out.content
assert "## 议题板块" in out.content

print("Minutes todo compliance: validate / repair / splice all pass")
