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
