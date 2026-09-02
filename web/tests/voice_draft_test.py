#!/usr/bin/env python3
"""长会议必须按稳定 T ID 分段，不能把超限请求交给模型服务。"""

from __future__ import annotations

import re
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))

from meeting_core.context_budget import ContextBudget, estimate_text_tokens  # noqa: E402
from meeting_core.llm import Completion  # noqa: E402
from meeting_core import voice_draft  # noqa: E402


class FakeClient:
    def __init__(self):
        self.calls = []

    def complete(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        ids = re.findall(r"T\d{6}", prompt)
        if "meeting-minutes-chunk/v1" in prompt:
            content = f"- 合成片段事实，依据 {ids[0]}、{ids[-1]}"
        else:
            content = ("# 会议纪要\n\n## 总体摘要\n\n- 合成测试结论\n\n"
                       "### 待办事项\n\n未形成明确待办\n\n"
                       "### 风险/待确认\n\n- 无\n\n## 议题详情\n\n- 合成议题。")
        return Completion(content=content,
                          usage={"prompt_tokens": 100, "completion_tokens": 20},
                          elapsed=0.01)


turns = []
for index in range(520):
    turns.append({
        "id": f"T{index + 1:06d}", "index": index,
        "start": float(index * 5), "end": float(index * 5 + 4),
        "speaker": "合成说话人", "voice_id": None, "person_id": None,
        "page_id": None,
        "text": "这是完全虚构的长会议测试内容，用于验证上下文预算与连续分段。" * 6,
    })
context = {
    "schema": "meeting-minutes-prompt/v1",
    "speaker_profiles": [], "pages": [], "turns": turns,
    "materials": [
        {"id": "F0001", "nearby_turn_ids": ["T000001"], "visual_summary": "合成白板甲"},
        {"id": "F0002", "nearby_turn_ids": ["T000520"], "visual_summary": "合成白板乙"},
        {"id": "F0003", "nearby_turn_ids": [], "visual_summary": "未定位资料"},
    ],
}
policy = {"version": "synthetic/v1", "rules": ["不得编造"]}
direct = voice_draft.build_direct_prompt(context, policy)
assert not ContextBudget(output_tokens=8192).fits(direct)

client = FakeClient()
result = voice_draft.generate(context, policy, client=client, max_tokens=8192)
assert result.mode == "map_reduce"
assert result.chunks > 1
assert len(client.calls) == result.chunks + 1
assert "T000001" in client.calls[0][0]
assert "T000520" in client.calls[-2][0]
assert "F0001" in client.calls[0][0] and "F0002" not in client.calls[0][0]
assert "F0002" in client.calls[-2][0] and "F0001" not in client.calls[-2][0]
assert "F0003" not in client.calls[0][0] and "F0003" in client.calls[-1][0]
assert client.calls[-1][1]["max_tokens"] == 8192
for prompt, kwargs in client.calls[:-1]:
    assert kwargs["max_tokens"] == 2048
    assert estimate_text_tokens(prompt) < 30000
assert result.content.startswith("# 会议纪要")

print(f"Voice draft: long context split into {result.chunks} stable-ID chunks")
