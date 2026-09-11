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
           "pages": pages, "turns": turns,
           "materials": [
               {"id": "F0001", "nearby_turn_ids": ["T000001"],
                "visual_summary": "合成现场资料甲"},
               {"id": "F0002", "nearby_turn_ids": ["T000620"],
                "visual_summary": "合成现场资料乙"},
               {"id": "F0003", "nearby_turn_ids": [],
                "visual_summary": "未定位现场资料"},
           ],
           "voice_draft_checklist": {
               "schema": "meeting-voice-draft-checklist/v1",
               "items": [{"draft_claim_id": "C00001", "kind": "action",
                           "status": "open", "formal_action": True,
                           "turn_ids": ["T000002"], "text": "合成待办"}],
           }}
client = FakeClient()
result = generate(context, {"version": "synthetic/v1"}, "只使用合成证据。",
                  client=client)
assert result.mode == "map_reduce"
assert result.chunks > 1
assert len(client.calls) == result.chunks + 1
assert "T000001" in client.calls[0][0]
assert "T000620" in client.calls[-2][0]
assert "P0001" in client.calls[0][0]
assert "F0001" in client.calls[0][0] and "F0002" not in client.calls[0][0]
assert "F0002" in client.calls[-2][0] and "F0001" not in client.calls[-2][0]
assert "F0003" not in client.calls[0][0] and "F0003" in client.calls[-1][0]
assert "meeting-voice-draft-checklist/v1" in client.calls[0][0]
assert "meeting-voice-draft-checklist/v1" in client.calls[-1][0]
assert "T000002" in client.calls[-1][0]
assert client.calls[-1][1]["max_tokens"] == 6144
assert all(call[1]["max_tokens"] == 1400 for call in client.calls[:-1])
assert result.content.startswith("## 总体摘要")

print(f"Minutes overview: long multimodal context split into {result.chunks} chunks")

# A bounded retry uses original evidence, never the truncated candidate.
from meeting_core.llm import LLMTruncatedError, LLMResponseError
from meeting_core.minutes_overview import _complete_with_guard

class TruncatingClient:
    def __init__(self, failures=1):
        self.calls = []
        self.failures = failures

    def complete(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        if len(self.calls) <= self.failures:
            raise LLMTruncatedError('synthetic truncation')
        return Completion('完整合成笔记 T000001', {}, 0.1)

retry_client = TruncatingClient()
assert _complete_with_guard(retry_client, '原始合成证据 T000001', max_tokens=1400).content
assert [c[1]['max_tokens'] for c in retry_client.calls] == [1400, 2800]
assert retry_client.calls[0][0] == retry_client.calls[1][0]
failing = TruncatingClient(10)
try:
    _complete_with_guard(failing, '合成证据', max_tokens=1400)
    raise AssertionError('truncated output accepted')
except LLMResponseError:
    assert len(failing.calls) == 2

from copy import deepcopy
from meeting_core.minutes_overview import synthesis_context

raw = {'pages': [{'id': 'P0001', 'number': 1, 'first': 3.0,
    'ranges': [[3.0, 8.0]], 'visual_summary': '虚构预测', 'visual_observation': {
        'summary': '虚构预测', 'facts': [{'raw_value': '12%', 'unit': '%',
            'qualifier': '预测，非实际', 'region': {'left': 0.1}}],
        'tables': [{'rows': [['甲', None]], 'notes': ['缺失单元格待核']}],
        'table_notes': ['缺失单元格待核'], 'chart_notes': ['独立补充，必须保留'],
        'unresolved': [{'question': '两处单位矛盾', 'region': None}],
    }}]}
before = deepcopy(raw)
compact = synthesis_context(raw)
assert raw == before and synthesis_context(compact) == compact
page = compact['pages'][0]
assert page['id'] == 'P0001' and page['first'] == 3.0
assert 'ranges' not in page and 'visual_summary' not in page
obs = page['visual_observation']
assert obs['facts'] == [{'raw_value': '12%', 'unit': '%', 'qualifier': '预测，非实际'}]
assert obs['tables'] == raw['pages'][0]['visual_observation']['tables']
assert obs['unresolved'] == [{'question': '两处单位矛盾'}]
assert 'table_notes' not in obs and obs['chart_notes'] == ['独立补充，必须保留']
