#!/usr/bin/env python3
"""验证 Topic Map 的尺度、证据过滤和非连续时间范围（全虚构数据）。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
import meeting_topic_map as topic_map  # noqa: E402


with tempfile.TemporaryDirectory(prefix="meeting-topic-map-") as tmp:
    mdir = Path(tmp) / "meetings" / "synthetic"
    mdir.mkdir(parents=True)
    turns = [
        {"speaker": "Alex", "start": 0, "end": 20, "text": "讨论虚构问题甲。"},
        {"speaker": "Bo", "start": 120, "end": 150, "text": "比较虚构方案甲乙。"},
        {"speaker": "Alex", "start": 600, "end": 630, "text": "回到问题甲并形成结论。"},
        {"speaker": "Bo", "start": 900, "end": 930, "text": "安排虚构后续动作。"},
    ]
    minutes = """# 会议纪要

## 总体摘要

- 问题甲形成结论。 <!-- mm:evidence kind=decision status=confirmed confidence=high turns=T000001,T000003 -->
- 安排后续动作。 <!-- mm:evidence kind=action status=open confidence=high turns=T000004 -->
"""
    (mdir / "transcript.spk.json").write_text(
        json.dumps(turns, ensure_ascii=False), encoding="utf-8")
    (mdir / "minutes.md").write_text(minutes, encoding="utf-8")
    (mdir / "slides.json").write_text("[]", encoding="utf-8")

    calls = []

    def fake_llm(prompt: str, _max_tokens: int):
        calls.append(prompt)
        if "meeting-topic-reduce-input/v1" not in prompt:
            ids = list(dict.fromkeys(__import__("re").findall(r"T\d{6}", prompt)))
            return {"summary": "合成窗口", "candidate_topics": [{
                "title": "合成候选", "summary": "局部推进", "turn_ids": ids,
                "claim_ids": [], "page_ids": [],
            }]}
        return {"meeting_summary": "围绕问题、方案和执行推进。", "topics": [
            {"title": "问题甲", "summary": "跨两个时间段讨论并形成结论。",
             "turn_ids": ["T000001", "T000003", "T999999"],
             "claim_ids": ["C00001"], "page_ids": [], "children": [
                 {"type": "argument", "title": "问题背景", "summary": "提出问题。",
                  "turn_ids": ["T000001"], "claim_ids": [], "page_ids": []},
                 {"type": "decision", "title": "形成结论", "summary": "完成收口。",
                  "turn_ids": ["T000003"], "claim_ids": ["C00001"], "page_ids": []},
             ]},
            {"title": "后续执行", "summary": "安排动作。", "turn_ids": ["T000004"],
             "claim_ids": ["C00002"], "page_ids": [], "children": [
                 {"type": "action", "title": "执行安排", "summary": "落实动作。",
                  "turn_ids": ["T000004"], "claim_ids": ["C00002"], "page_ids": []},
             ]},
        ]}

    path, result = topic_map.generate_topic_map(
        mdir, llm=fake_llm, model="synthetic-model", chunk_seconds=300)
    assert path.is_file() and result["schema"] == topic_map.SCHEMA
    assert len(result["topics"]) == 2
    assert result["topics"][0]["turn_ids"] == ["T000001", "T000003"]
    assert result["topics"][0]["ranges"] == [[0.0, 20.0], [600.0, 630.0]]
    assert result["topics"][0]["children"][1]["type"] == "decision"
    assert result["generation"]["window_count"] >= 2
    assert topic_map.load_current_topic_map(mdir)[0] == "ready"
    (mdir / "minutes.md").write_text(minutes + "\n", encoding="utf-8")
    assert topic_map.load_current_topic_map(mdir)[0] == "stale"
    assert len(calls) == result["generation"]["window_count"] + 1

with tempfile.TemporaryDirectory(prefix="meeting-topic-map-repair-") as tmp:
    mdir = Path(tmp) / "synthetic"
    mdir.mkdir()
    (mdir / "transcript.spk.json").write_text(json.dumps([
        {"speaker": "Alex", "start": 0, "end": 12, "text": "虚构讨论。"}
    ], ensure_ascii=False), encoding="utf-8")
    (mdir / "minutes.md").write_text(
        "# 会议纪要\n\n- 虚构结论。 <!-- mm:evidence kind=decision status=confirmed "
        "confidence=high turns=T000001 -->\n", encoding="utf-8")
    (mdir / "slides.json").write_text("[]", encoding="utf-8")
    repair_calls = []

    def malformed_then_repair(prompt: str, _max_tokens: int):
        repair_calls.append(prompt)
        if "严格的 JSON 格式修复器" in prompt:
            return {"meeting_summary": "虚构推进。", "topics": [{
                "title": "虚构论点", "summary": "形成结论。", "turn_ids": ["T000001"],
                "claim_ids": ["C00001"], "page_ids": [], "children": [{
                    "type": "decision", "title": "虚构结论", "summary": "完成收束。",
                    "turn_ids": ["T000001"], "claim_ids": ["C00001"], "page_ids": [],
                }],
            }]}
        if "meeting-topic-reduce-input/v1" in prompt:
            return '{"meeting_summary":"虚构推进","topics":[{"title":"虚构论点" "summary":"缺逗号"}]}'
        return {"summary": "虚构窗口", "candidate_topics": []}

    _, repaired = topic_map.generate_topic_map(
        mdir, llm=malformed_then_repair, model="synthetic-repair", chunk_seconds=300)
    assert repaired["stats"]["topics"] == 1
    assert any("严格的 JSON 格式修复器" in prompt for prompt in repair_calls)
    assert not (mdir / ".topic-map-work.json").exists()

print("Meeting Topic Map: map-reduce, evidence filtering, revisions, JSON repair passed")
