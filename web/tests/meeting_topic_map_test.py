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
    # T000002 未被模型挂接,确定性兜底按时间邻接挂到最近的论点一,只扩展 turn_ids/ranges。
    assert result["topics"][0]["turn_ids"] == ["T000001", "T000003", "T000002"]
    assert result["topics"][0]["ranges"] == [[0.0, 20.0], [120.0, 150.0], [600.0, 630.0]]
    assert result["topics"][0]["children"][1]["type"] == "decision"
    assert result["topics"][0]["low_value"] is False
    assert result["generation"]["window_count"] >= 2
    # coverage = ranges 并集(110s) ÷ 会议时长(0–930s)。
    assert abs(result["stats"]["coverage"] - 110 / 930) < 1e-3
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
            ids = list(dict.fromkeys(__import__("re").findall(r"T\d{6}", prompt)))
            return {"summary": "虚构窗口", "candidate_topics": [{
                "title": "虚构候选", "summary": "局部推进", "turn_ids": ids,
                "claim_ids": [], "page_ids": [],
            }]}
        # 模型只挂接 T000001 与 T000003;T000002/T000004 两段未覆盖区间由代码兜底按时间邻接分配。
        return {"meeting_summary": "虚构推进。", "topics": [
            {"title": "虚构议题", "summary": "开场与收口。", "turn_ids": ["T000001"],
             "claim_ids": [], "page_ids": [], "children": []},
            {"title": "过渡与杂项", "summary": "弱价值过渡。", "low_value": True,
             "turn_ids": ["T000003"], "claim_ids": [], "page_ids": [], "children": []},
        ]}

    _, covered = topic_map.generate_topic_map(
        mdir, llm=sparse_reduce_llm, model="synthetic-coverage", chunk_seconds=900)
    first, second = covered["topics"]
    # T000002(100–110) 距论点一更近;T000004(600–610) 距"过渡与杂项"(400–410)更近。
    assert first["turn_ids"] == ["T000001", "T000002"]
    assert first["ranges"] == [[0.0, 10.0], [100.0, 110.0]]
    assert first["summary"] == "开场与收口。"  # 兜底不改写模型文本
    assert first["low_value"] is False
    assert second["turn_ids"] == ["T000003", "T000004"]
    assert second["ranges"] == [[400.0, 410.0], [600.0, 610.0]]
    assert second["low_value"] is True  # low_value 标记透传到输出 topic
    # coverage = 并集 40s ÷ 610s。
    assert abs(covered["stats"]["coverage"] - 40 / 610) < 1e-3
    assert covered["stats"]["topics"] == 2

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
    assert fallback["generation"]["strategy"] == "map-reduce/local-candidates-fallback-v1"
    assert {turn_id for topic in fallback["topics"] for turn_id in topic["turn_ids"]} == {
        "T000001", "T000002", "T000003"}
    assert not (mdir / ".topic-map-work.json").exists()

print("Meeting Topic Map: map-reduce, evidence filtering, revisions, JSON repair, "
      "unrepairable chunk fallback, reduce retry/fallback, full coverage, low_value, "
      "v1 compat passed")
