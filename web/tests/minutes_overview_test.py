#!/usr/bin/env python3
"""多模态总体纪要超限时必须保留 T/P ID 分段归纳。"""

from __future__ import annotations

import re
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))

from meeting_core.llm import Completion  # noqa: E402
from meeting_core.minutes_overview import generate  # noqa: E402


class FakeClient:
    def __init__(self):
        self.calls = []

    def complete(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        tids = re.findall(r"T\d{6}", prompt)
        pids = re.findall(r"P\d{4}", prompt)
        if "overview-chunk/v1" in prompt:
            content = f"- 合成事实 {tids[0]} {tids[-1]} {pids[0] if pids else ''}"
        else:
            content = ("## 总体摘要\n- **主旨**：合成会议。\n\n"
                       "### 待办事项\n未形成明确待办\n\n"
                       "### 风险/待确认\n- 无\n\n"
                       "## 议题板块\n- 合成议题（第1–2页，00:00 起）：合成说明。")
        return Completion(content=content,
                          usage={"prompt_tokens": 100, "completion_tokens": 20},
                          elapsed=0.01)


turns = []
for index in range(620):
    turns.append({
        "id": f"T{index + 1:06d}", "index": index,
        "start": index * 5.0, "end": index * 5.0 + 4,
        "speaker": "合成说话人", "voice_id": None, "person_id": None,
        "page_id": f"P{index // 100 + 1:04d}",
        "text": "完全虚构的多模态长会议事实，用于验证上下文预算。" * 6,
    })
pages = [{"id": f"P{number:04d}", "number": number,
          "first": (number - 1) * 500.0, "ranges": [],
          "visual_summary": "合成页面数据表"}
         for number in range(1, 8)]
context = {"schema": "meeting-minutes-prompt/v1", "speaker_profiles": [],
           "pages": pages, "turns": turns}
client = FakeClient()
result = generate(context, {"version": "synthetic/v1"}, "只使用合成证据。",
                  client=client)
assert result.mode == "map_reduce"
assert result.chunks > 1
assert len(client.calls) == result.chunks + 1
assert "T000001" in client.calls[0][0]
assert "T000620" in client.calls[-2][0]
assert "P0001" in client.calls[0][0]
assert client.calls[-1][1]["max_tokens"] == 8192
assert result.content.startswith("## 总体摘要")

print(f"Minutes overview: long multimodal context split into {result.chunks} chunks")
