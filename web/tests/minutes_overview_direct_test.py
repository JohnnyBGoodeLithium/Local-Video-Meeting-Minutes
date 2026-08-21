#!/usr/bin/env python3
"""直出总体纪要必须与 map/reduce 共用退化/章节/待办合规护栏（全虚构数据）。

真实事故：77 分钟会议直出稿的总体章节零证据标记、待办表格无 kind=action
标记，导致正式待办整表为空。直出路径曾完全绕过 map/reduce 的护栏。
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))

from meeting_core.llm import Completion  # noqa: E402
from meeting_core.minutes_overview import generate_direct  # noqa: E402


GOOD = ("## 总体摘要\n- **主旨**：合成会议。\n\n"
        "### 待办事项\n\n"
        "| 事项 | 负责人 | 期限 | 状态 |\n"
        "| --- | --- | --- | --- |\n"
        "| 完成合成验证 | Alex Example | 周五 | "
        "<!-- mm:evidence kind=action status=confirmed confidence=high turns=T000001 --> |\n\n"
        "### 风险/待确认\n- 无\n")

BAD_TODO = ("## 总体摘要\n- **主旨**：合成会议。\n\n"
            "### 待办事项\n\n"
            "| 事项 | 负责人 | 期限 | 状态 |\n"
            "| --- | --- | --- | --- |\n"
            "| 完成合成验证 | Alex Example | 周五 | 已确认 |\n\n"
            "### 风险/待确认\n- 无\n")

REPAIRED_TODO = ("### 待办事项\n\n"
                 "| 事项 | 负责人 | 期限 | 状态 |\n"
                 "| --- | --- | --- | --- |\n"
                 "| 完成合成验证 | Alex Example | 周五 | "
                 "<!-- mm:evidence kind=action status=confirmed confidence=high turns=T000001 --> |\n")

OUTSIDE_ACTION = ("## 总体摘要\n- **主旨**：合成会议。\n\n"
                  "### 待办事项\n未形成明确待办\n\n"
                  "### 风险/待确认\n- 无\n\n"
                  "## 议题详情\n- 明确安排合成验证。 "
                  "<!-- mm:evidence kind=action status=confirmed confidence=high turns=T000001 -->\n")


class SequenceClient:
    def __init__(self, outputs, *, usage=None):
        self.outputs = list(outputs)
        self.calls = []
        self.usage = usage or {"prompt_tokens": 10, "completion_tokens": 5}

    def complete(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        content = self.outputs.pop(0)
        return Completion(content=content,
                          usage=self.usage,
                          elapsed=0.01)


# 1. 直出即合规：只调用一次，不重试不修复
client = SequenceClient([GOOD])
result = generate_direct("合成直出 prompt", "只使用合成证据。", notes="合成上下文",
                         client=client)
assert result.content == GOOD
assert len(client.calls) == 1

# 2. 待办不合规 → 重试一次仍不合规 → 定点修复合规 → 拼接回终稿
client = SequenceClient([BAD_TODO, BAD_TODO, REPAIRED_TODO])
result = generate_direct("合成直出 prompt", "只使用合成证据。", notes="合成上下文含 T000001",
                         client=client)
assert len(client.calls) == 3
assert "kind=action" in result.content and "turns=T000001" in result.content
assert "## 总体摘要" in result.content  # 修复只替换待办章节，其余保留
# 修复轮 prompt 必须携带完整上下文（直出没有片段笔记）和原待办章节
assert "合成上下文含 T000001" in client.calls[-1][0]
assert "完成合成验证" in client.calls[-1][0]

# 3. 修复也不合规：保留原稿，不得产出无标记待办之外的伪造内容
client = SequenceClient([BAD_TODO, BAD_TODO, BAD_TODO, BAD_TODO])
result = generate_direct("合成直出 prompt", "只使用合成证据。", notes="合成上下文",
                         client=client)
assert result.content == BAD_TODO
assert len(client.calls) == 4  # 初稿 + 重试 + 修复 + 修复重试

# 4. 缺必需章节（总体摘要）→ 触发重试
client = SequenceClient(["### 待办事项\n未形成明确待办\n", GOOD])
result = generate_direct("合成直出 prompt", "只使用合成证据。", notes="合成上下文",
                         client=client)
assert result.content == GOOD
assert len(client.calls) == 2
assert client.calls[-1][1].get("repeat_penalty") == 1.2

# 5. 待办写“无”但议题详情出现 action marker：这是漏投影而不是合规空待办，必须重试。
client = SequenceClient([OUTSIDE_ACTION, GOOD])
result = generate_direct("合成直出 prompt", "只使用合成证据。", notes="合成上下文含 T000001",
                         client=client)
assert result.content == GOOD and len(client.calls) == 2

# 6. 重试仍漏投影时由修复轮补入正式待办；详情 marker 降为 discussion，避免双重 action。
client = SequenceClient([OUTSIDE_ACTION, OUTSIDE_ACTION, REPAIRED_TODO])
result = generate_direct("合成直出 prompt", "只使用合成证据。", notes="合成上下文含 T000001",
                         client=client)
assert result.content.count("kind=action") == 1
assert "kind=discussion status=confirmed" in result.content

# 7. llama.cpp/OpenAI-compatible usage 可含嵌套 token 明细；待办定点修复只能
# 汇总数值计数，不能因统计对象无法 int() 而把已经生成的纪要判为失败。
client = SequenceClient(
    [BAD_TODO, BAD_TODO, REPAIRED_TODO],
    usage={"prompt_tokens": 10, "completion_tokens": 5,
           "prompt_tokens_details": {"cached_tokens": 3}},
)
result = generate_direct(
    "合成直出 prompt", "只使用合成证据。", notes="合成上下文含 T000001",
    client=client)
assert "kind=action" in result.content
assert result.usage == {"prompt_tokens": 20, "completion_tokens": 10}

print("Minutes overview direct: guard, retry and todo repair passed")
