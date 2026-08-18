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


# JSON 解析边界只能清 reasoning，不能复用会删除独占花括号的 VL 人读清洗器。
assert topic_map._model_json('''```json
{
  "meeting_summary": "虚构格式回归",
  "topics": []
}
```''')["meeting_summary"] == "虚构格式回归"


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
             "candidate_ids": ["W001C01", "W002C01"],
             "turn_ids": ["T000001", "T000003", "T999999"],
             "claim_ids": ["C00001"], "page_ids": [], "children": [
                 {"type": "argument", "title": "问题背景", "summary": "提出问题。",
                  "turn_ids": ["T000001"], "claim_ids": [], "page_ids": []},
                 {"type": "decision", "title": "形成结论", "summary": "完成收口。",
                  "turn_ids": ["T000003"], "claim_ids": ["C00001"], "page_ids": []},
             ]},
            {"title": "后续执行", "summary": "安排动作。", "turn_ids": ["T000004"],
             "candidate_ids": ["W003C01"],
             "claim_ids": ["C00002"], "page_ids": [], "children": [
                 {"type": "action", "title": "执行安排", "summary": "落实动作。",
                  "turn_ids": ["T000004"], "claim_ids": ["C00002"], "page_ids": []},
             ]},
        ]}

    path, result = topic_map.generate_topic_map(
        mdir, llm=fake_llm, model="synthetic-model", chunk_seconds=300)
    assert path.is_file() and result["schema"] == topic_map.SCHEMA
    assert len(result["topics"]) == 2
    # 代表论据保持精简；局部候选吸收关系只扩展导航，不污染可审计的 turn_ids。
    assert result["topics"][0]["turn_ids"] == ["T000001", "T000003"]
    assert result["topics"][0]["navigation_turn_ids"] == [
        "T000001", "T000002", "T000003"]
    assert result["topics"][0]["ranges"] == [[0.0, 20.0], [120.0, 150.0], [600.0, 630.0]]
    assert result["topics"][0]["children"][1]["type"] == "decision"
    assert result["topics"][0]["low_value"] is False
    assert result["generation"]["window_count"] >= 2
    assert result["stats"]["coverage"] == 1.0
    assert abs(result["stats"]["time_coverage"] - 110 / 930) < 1e-3
    assert result["stats"]["navigation_coverage"] == 1.0
    assert result["stats"]["evidence_turn_coverage"] == 0.75
    assert result["stats"]["candidate_turns_recovered"] == 1
    assert "uncovered_turn_ids" in calls[0]
    assert "low_value" in calls[-1]
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

with tempfile.TemporaryDirectory(prefix="meeting-topic-chunk-repair-") as tmp:
    mdir = Path(tmp) / "synthetic"
    mdir.mkdir()
    (mdir / "transcript.spk.json").write_text(json.dumps([
        {"speaker": "Alex", "start": 0, "end": 12, "text": "虚构讨论。"}
    ], ensure_ascii=False), encoding="utf-8")
    (mdir / "minutes.md").write_text(
        "# 会议纪要\n\n- 虚构结论。 <!-- mm:evidence kind=decision status=confirmed "
        "confidence=high turns=T000001 -->\n", encoding="utf-8")
    (mdir / "slides.json").write_text("[]", encoding="utf-8")
    chunk_calls = []

    def malformed_chunk_then_repair(prompt: str, _max_tokens: int):
        chunk_calls.append(prompt)
        if "严格的 JSON 格式修复器" in prompt:
            return {"summary": "虚构窗口", "candidate_topics": [{
                "title": "虚构候选", "summary": "局部推进", "turn_ids": ["T000001"],
                "claim_ids": ["C00001"], "page_ids": [],
            }]}
        if "meeting-topic-reduce-input/v1" in prompt:
            return {"meeting_summary": "虚构推进。", "topics": [{
                "title": "虚构论点", "summary": "形成结论。", "turn_ids": ["T000001"],
                "claim_ids": ["C00001"], "page_ids": [], "children": [],
            }]}
        return '{"summary":"虚构窗口" "candidate_topics":[]}'

    _, repaired_chunk = topic_map.generate_topic_map(
        mdir, llm=malformed_chunk_then_repair, model="synthetic-chunk-repair",
        chunk_seconds=300)
    assert repaired_chunk["stats"]["topics"] == 1
    assert any("严格的 JSON 格式修复器" in prompt for prompt in chunk_calls)

with tempfile.TemporaryDirectory(prefix="meeting-topic-map-low-value-") as tmp:
    mdir = Path(tmp) / "synthetic"
    mdir.mkdir()
    (mdir / "transcript.spk.json").write_text(json.dumps([
        {"speaker": "Alex", "start": 0, "end": 10, "text": "虚构议题开场。"},
        {"speaker": "Bo", "start": 100, "end": 110, "text": "虚构寒暄等待。"},
        {"speaker": "Alex", "start": 400, "end": 410, "text": "虚构过渡闲谈。"},
        {"speaker": "Bo", "start": 600, "end": 610, "text": "虚构议题收口。"},
    ], ensure_ascii=False), encoding="utf-8")
    (mdir / "minutes.md").write_text(
        "# 会议纪要\n\n## 总体摘要\n\n- 虚构议题完成开场与收口。\n", encoding="utf-8")
    (mdir / "slides.json").write_text("[]", encoding="utf-8")

    def sparse_reduce_llm(prompt: str, _max_tokens: int):
        if "meeting-topic-reduce-input/v1" not in prompt:
            return {"summary": "虚构窗口", "candidate_topics": [{
                "title": "虚构候选", "summary": "业务开场与收口",
                "turn_ids": ["T000001", "T000004"],
                "claim_ids": [], "page_ids": [],
            }], "uncovered_turn_ids": ["T000002", "T000003"]}
        return {"meeting_summary": "虚构推进。", "topics": [{
            "title": "虚构议题", "summary": "开场与收口。",
            "candidate_ids": ["W001C01"], "turn_ids": ["T000001", "T000004"],
            "claim_ids": [], "page_ids": [], "children": [],
        }]}

    _, covered = topic_map.generate_topic_map(
        mdir, llm=sparse_reduce_llm, model="synthetic-coverage", chunk_seconds=900)
    first = covered["topics"][0]
    assert first["turn_ids"] == ["T000001", "T000004"]
    assert first["navigation_turn_ids"] == ["T000001", "T000004"]
    assert first["ranges"] == [[0.0, 10.0], [600.0, 610.0]]
    assert first["summary"] == "开场与收口。"  # 兜底不改写模型文本
    assert first["low_value"] is False
    segment_kinds = [segment["kind"] for segment in covered["navigation_segments"]]
    assert segment_kinds[0] == "topic" and segment_kinds[-1] == "topic"
    assert all(kind == "transition" for kind in segment_kinds[1:-1])
    assert covered["stats"]["coverage"] == 0.5
    assert covered["stats"]["navigation_coverage"] == 1.0
    assert covered["stats"]["transition_turns"] == 2
    assert covered["stats"]["unassigned_turns"] == 0
    assert covered["stats"]["topics"] == 1

with tempfile.TemporaryDirectory(prefix="meeting-topic-map-v1-") as tmp:
    mdir = Path(tmp) / "synthetic"
    mdir.mkdir()
    (mdir / "transcript.spk.json").write_text(json.dumps([
        {"speaker": "Alex", "start": 0, "end": 12, "text": "虚构讨论。"}
    ], ensure_ascii=False), encoding="utf-8")
    (mdir / "minutes.md").write_text("# 会议纪要\n\n- 虚构结论。\n", encoding="utf-8")
    (mdir / "slides.json").write_text("[]", encoding="utf-8")
    legacy = {
        "schema": "meeting-topic-map/v1", "state": "ready",
        "revisions": topic_map.current_revisions(mdir),
        "meeting_summary": "虚构旧图。",
        "topics": [{"id": "M01", "title": "虚构旧论点", "summary": "旧图内容。",
                    "turn_ids": ["T000001"], "claim_ids": [], "page_ids": [],
                    "ranges": [[0.0, 12.0]], "start": 0.0, "end": 12.0, "children": []}],
        "stats": {"topics": 1, "children": 0},
    }
    (mdir / "meeting.topic-map.json").write_text(
        json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    # v1 旧图 revisions 匹配仍判 ready,内容原样返回(无 coverage 字段)。
    state, loaded = topic_map.load_current_topic_map(mdir)
    assert state == "ready" and loaded["schema"] == "meeting-topic-map/v1"
    assert loaded["topics"][0]["id"] == "M01"
    assert "coverage" not in loaded["stats"]
    legacy["revisions"] = dict(legacy["revisions"], transcript="outdated")
    (mdir / "meeting.topic-map.json").write_text(
        json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    assert topic_map.load_current_topic_map(mdir)[0] == "stale"

with tempfile.TemporaryDirectory(prefix="meeting-topic-chunk-unrepairable-") as tmp:
    mdir = Path(tmp) / "synthetic"
    mdir.mkdir()
    (mdir / "transcript.spk.json").write_text(json.dumps([
        {"speaker": "Alex", "start": 0, "end": 12, "text": "虚构讨论。"}
    ], ensure_ascii=False), encoding="utf-8")
    (mdir / "minutes.md").write_text(
        "# 会议纪要\n\n- 虚构结论。 <!-- mm:evidence kind=decision status=confirmed "
        "confidence=high turns=T000001 -->\n", encoding="utf-8")
    (mdir / "slides.json").write_text("[]", encoding="utf-8")

    def unrepairable_chunk(prompt: str, _max_tokens: int):
        if "meeting-topic-reduce-input/v1" in prompt:
            return {"meeting_summary": "虚构推进。", "topics": [{
                "title": "虚构论点", "summary": "形成结论。", "turn_ids": ["T000001"],
                "claim_ids": ["C00001"], "page_ids": [], "children": [],
            }]}
        # 局部归纳与修复器都返回坏 JSON:单窗降级为空归纳,整场不失败。
        return '{"summary":"坏" "candidate_topics":'

    _, survived = topic_map.generate_topic_map(
        mdir, llm=unrepairable_chunk, model="synthetic-unrepairable", chunk_seconds=300)
    assert survived["stats"]["topics"] == 1
    assert not (mdir / ".topic-map-work.json").exists()

with tempfile.TemporaryDirectory(prefix="meeting-topic-reduce-retry-") as tmp:
    mdir = Path(tmp) / "synthetic"
    mdir.mkdir()
    (mdir / "transcript.spk.json").write_text(json.dumps([
        {"speaker": "Alex", "start": 0, "end": 12, "text": "虚构讨论。"}
    ], ensure_ascii=False), encoding="utf-8")
    (mdir / "minutes.md").write_text(
        "# 会议纪要\n\n- 虚构结论。 <!-- mm:evidence kind=decision status=confirmed "
        "confidence=high turns=T000001 -->\n", encoding="utf-8")
    (mdir / "slides.json").write_text("[]", encoding="utf-8")
    reduce_calls = []

    def reduce_retry_llm(prompt: str, _max_tokens: int):
        if "严格的 JSON 格式修复器" in prompt:
            return '{"meeting_summary":"仍然坏" "topics":'
        if "meeting-topic-reduce-input/v1" in prompt:
            reduce_calls.append(prompt)
            if len(reduce_calls) == 1:
                return '{"meeting_summary":"坏" "topics":'
            return {"meeting_summary": "虚构推进。", "topics": [{
                "title": "虚构论点", "summary": "形成结论。", "turn_ids": ["T000001"],
                "claim_ids": ["C00001"], "page_ids": [], "children": [],
            }]}
        return {"summary": "虚构窗口", "candidate_topics": []}

    _, retried = topic_map.generate_topic_map(
        mdir, llm=reduce_retry_llm, model="synthetic-reduce-retry", chunk_seconds=300)
    # 归并坏 JSON + 修复仍坏 → 完整重试一次后成功。
    assert len(reduce_calls) == 2
    assert retried["stats"]["topics"] == 1

with tempfile.TemporaryDirectory(prefix="meeting-topic-reduce-fallback-") as tmp:
    mdir = Path(tmp) / "synthetic"
    mdir.mkdir()
    (mdir / "transcript.spk.json").write_text(json.dumps([
        {"speaker": "Alex", "start": 0, "end": 10, "text": "虚构议题甲。"},
        {"speaker": "Bo", "start": 20, "end": 30, "text": "虚构议题乙。"},
        {"speaker": "Alex", "start": 40, "end": 50, "text": "虚构议题丙。"},
    ], ensure_ascii=False), encoding="utf-8")
    (mdir / "minutes.md").write_text(
        "# 会议纪要\n\n- 虚构结论。 <!-- mm:evidence kind=decision status=confirmed "
        "confidence=high turns=T000001 -->\n", encoding="utf-8")
    (mdir / "slides.json").write_text("[]", encoding="utf-8")

    def invalid_reduce_with_valid_candidates(prompt: str, _max_tokens: int):
        if "meeting-topic-reduce-input/v1" in prompt or "严格的 JSON 格式修复器" in prompt:
            return 'not-json'
        ids = list(dict.fromkeys(__import__("re").findall(r"T\d{6}", prompt)))
        return {"summary": "三个虚构议题。", "candidate_topics": [
            {"title": f"虚构议题{index}", "summary": f"推进虚构内容{index}。",
             "turn_ids": [turn_id], "claim_ids": [], "page_ids": []}
            for index, turn_id in enumerate(ids, 1)
        ]}

    _, fallback = topic_map.generate_topic_map(
        mdir, llm=invalid_reduce_with_valid_candidates,
        model="synthetic-reduce-fallback", chunk_seconds=300)
    assert fallback["stats"]["topics"] == 3
    assert fallback["generation"]["strategy"] == "map-reduce/local-candidates-fallback-v3"
    assert {turn_id for topic in fallback["topics"] for turn_id in topic["turn_ids"]} == {
        "T000001", "T000002", "T000003"}
    assert not (mdir / ".topic-map-work.json").exists()

# 一级议题主归属必须互斥；长段未知内容不得为了“看起来全覆盖”硬塞给最近标题。
source_turns = [{
    "id": f"T{index + 1:06d}", "index": index,
    "start": float(index * 60), "end": float(index * 60 + 10),
    "speaker": "Synthetic", "text": f"虚构轮次 {index + 1}",
} for index in range(10)]
synthetic_evidence = {
    "sources": {"transcript": source_turns, "pages": []},
    "claims": [],
}
overlap_raw = {"meeting_summary": "虚构重叠。", "topics": [
    {"title": "议题甲", "summary": "前段。",
     "turn_ids": [f"T{i:06d}" for i in range(1, 5)], "claim_ids": [], "page_ids": [],
     "children": []},
    {"title": "议题乙", "summary": "后段。",
     "turn_ids": [f"T{i:06d}" for i in range(3, 7)], "claim_ids": [], "page_ids": [],
     "children": []},
]}
deduped = topic_map._sanitize_map(
    overlap_raw, synthetic_evidence, {}, model="synthetic-overlap",
    window_count=1, chunk_seconds=900)
assert deduped["topics"][0]["turn_ids"] == [f"T{i:06d}" for i in range(1, 5)]
assert deduped["topics"][1]["turn_ids"] == ["T000005", "T000006"]
assert deduped["stats"]["overlap_turns_removed"] == 2
assert not (set(deduped["topics"][0]["turn_ids"]) & set(deduped["topics"][1]["turn_ids"]))

# 前一议题的跨段 claim 不得吞掉后一议题显式指定的唯一轮次。
claim_spanning_evidence = {
    "sources": {"transcript": source_turns[:3], "pages": []},
    "claims": [{"id": "C00001", "turn_ids": ["T000001", "T000002"], "page_ids": []}],
}
claim_overlap_raw = {"meeting_summary": "虚构跨段结论。", "topics": [
    {"title": "议题甲", "summary": "前段。", "turn_ids": ["T000001"],
     "claim_ids": ["C00001"], "page_ids": [], "children": []},
    {"title": "议题乙", "summary": "后段。", "turn_ids": ["T000002"],
     "claim_ids": [], "page_ids": [], "children": []},
]}
claim_deduped = topic_map._sanitize_map(
    claim_overlap_raw, claim_spanning_evidence, {}, model="synthetic-claim-overlap",
    window_count=1, chunk_seconds=900)
assert len(claim_deduped["topics"]) == 2
assert claim_deduped["topics"][0]["turn_ids"] == ["T000001"]
assert "T000002" in claim_deduped["topics"][1]["turn_ids"]
assert "T000002" not in claim_deduped["topics"][0]["turn_ids"]

# v2 兼容辅助函数仍可继承局部引用；v3 正常生成不再调用它污染代表论据。
representative_raw = {"meeting_summary": "虚构代表引用。", "topics": [
    {"title": "议题甲", "summary": "前段。", "turn_ids": ["T000001"],
     "claim_ids": [], "page_ids": [], "children": []},
    {"title": "议题乙", "summary": "后段。", "turn_ids": ["T000005"],
     "claim_ids": [], "page_ids": [], "children": []},
]}
candidate_summaries = [{"candidate_topics": [
    {"title": "候选甲", "turn_ids": ["T000001", "T000002", "T000003"],
     "claim_ids": [], "page_ids": []},
    {"title": "候选乙", "turn_ids": ["T000005", "T000006"],
     "claim_ids": [], "page_ids": []},
    {"title": "无锚候选", "turn_ids": ["T000009"], "claim_ids": [], "page_ids": []},
]}]
expanded = topic_map._expand_candidate_refs(representative_raw, candidate_summaries)
assert expanded["topics"][0]["turn_ids"] == ["T000001", "T000002", "T000003"]
assert expanded["topics"][1]["turn_ids"] == ["T000005", "T000006"]
assert expanded["_candidate_turns_recovered"] == 3
assert "T000009" not in {tid for topic in expanded["topics"] for tid in topic["turn_ids"]}

# v3 通过 candidate_ids 建立全量导航；未被候选吸收的轮次必须显式标为未知。
v3_summaries = [{"candidate_topics": [
    {"candidate_id": "W001C01", "title": "候选甲",
     "turn_ids": ["T000001", "T000002", "T000003"],
     "claim_ids": [], "page_ids": []},
    {"candidate_id": "W001C02", "title": "候选乙",
     "turn_ids": ["T000005", "T000006"],
     "claim_ids": [], "page_ids": []},
]}]
v3_raw = {"meeting_summary": "虚构导航。", "topics": [
    {"title": "议题甲", "summary": "前段。", "candidate_ids": ["W001C01"],
     "turn_ids": ["T000001"], "claim_ids": [], "page_ids": [], "children": []},
    {"title": "议题乙", "summary": "后段。", "candidate_ids": ["W001C02"],
     "turn_ids": ["T000005"], "claim_ids": [], "page_ids": [], "children": []},
]}
v3_navigation = topic_map._sanitize_map(
    v3_raw, synthetic_evidence, {}, model="synthetic-v3",
    window_count=1, chunk_seconds=900, summaries=v3_summaries)
assert v3_navigation["topics"][0]["turn_ids"] == ["T000001"]
assert v3_navigation["topics"][0]["navigation_turn_ids"] == [
    "T000001", "T000002", "T000003"]
assert v3_navigation["stats"]["candidate_turns_recovered"] == 3
assert v3_navigation["stats"]["unassigned_turns"] == 5
assert any(segment["kind"] == "unclassified"
           for segment in v3_navigation["navigation_segments"])

# 时间线是章节导航：同一议题之间的短回应应归回该议题，不展示为碎片。
short_bridge_turns = [
    {"id": "T000001", "start": 0.0, "end": 20.0},
    {"id": "T000002", "start": 20.0, "end": 32.0},
    {"id": "T000003", "start": 32.0, "end": 50.0},
]
short_bridge_topics = [{
    "id": "M01", "turn_ids": ["T000001", "T000003"],
    "ranges": [[0.0, 20.0], [32.0, 50.0]], "candidate_ids": ["W001C01"],
}]
short_bridge_summaries = [{
    "uncovered_turn_ids": ["T000002"],
    "candidate_topics": [{
        "candidate_id": "W001C01", "turn_ids": ["T000001", "T000003"],
    }],
}]
short_segments, short_stats = topic_map._apply_navigation(
    short_bridge_topics, short_bridge_summaries, short_bridge_turns)
assert len(short_segments) == 1 and short_segments[0]["kind"] == "topic"
assert short_segments[0]["ranges"] == [[0.0, 50.0]]
assert short_bridge_topics[0]["navigation_turn_ids"] == [
    "T000001", "T000002", "T000003"]
assert short_bridge_topics[0]["ranges"] == [[0.0, 50.0]]
assert short_stats["transition_turns"] == 0 and short_stats["coverage"] == 1.0

# DOCX 连续发言可能共用粗粒度时间戳；导航投影必须按顺序切开而不重叠。
disjoint = topic_map._coalesce_navigation_segments([
    {"id": "S001", "kind": "topic", "topic_id": "M01",
     "turn_ids": ["T000001"], "ranges": [[90.0, 137.0]]},
    {"id": "S002", "kind": "topic", "topic_id": "M02",
     "turn_ids": ["T000002"], "ranges": [[90.0, 146.0]]},
])
assert disjoint[0]["end"] == disjoint[1]["start"]
assert disjoint[0]["end"] == 113.5

# 存量 v3 文件读取时也确定性收敛，无需重跑 LLM。
stored = topic_map._normalize_v3_navigation({
    "schema": topic_map.SCHEMA,
    "topics": [{"id": "M01", "turn_ids": ["T000001", "T000003"],
                "ranges": [[0.0, 20.0], [32.0, 50.0]]}],
    "navigation_segments": [
        {"id": "S001", "kind": "topic", "topic_id": "M01",
         "turn_ids": ["T000001"], "ranges": [[0.0, 20.0]]},
        {"id": "S002", "kind": "transition", "topic_id": None,
         "turn_ids": ["T000002"], "ranges": [[20.0, 32.0]]},
        {"id": "S003", "kind": "topic", "topic_id": "M01",
         "turn_ids": ["T000003"], "ranges": [[32.0, 50.0]]},
    ],
    "stats": {},
})
assert stored["topics"][0]["ranges"] == [[0.0, 50.0]]
assert stored["topics"][0]["navigation_turn_ids"] == [
    "T000001", "T000002", "T000003"]
assert len(stored["navigation_segments"]) == 1

gap_raw = {"meeting_summary": "虚构稀疏覆盖。", "topics": [
    {"title": "锚点一", "summary": "开场。", "turn_ids": ["T000001"],
     "claim_ids": [], "page_ids": [], "children": []},
    {"title": "锚点二", "summary": "中段。", "turn_ids": ["T000005"],
     "claim_ids": [], "page_ids": [], "children": []},
    {"title": "锚点三", "summary": "收口。", "turn_ids": ["T000010"],
     "claim_ids": [], "page_ids": [], "children": []},
]}
honest_gaps = topic_map._sanitize_map(
    gap_raw, synthetic_evidence, {}, model="synthetic-gaps",
    window_count=1, chunk_seconds=900)
assert honest_gaps["stats"]["unassigned_turns"] == 7
assert honest_gaps["stats"]["turn_coverage"] == 0.3
assert "T000002" not in {tid for topic in honest_gaps["topics"] for tid in topic["turn_ids"]}

print("Meeting Topic Map v3: evidence/navigation split, candidate mapping, chapter-scale "
      "coalescing, DOCX timestamp normalization, reduce fallback and v1 compat passed")
