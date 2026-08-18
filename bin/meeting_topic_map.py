#!/usr/bin/env python3
"""用本机 LLM 把逐字稿/evidence 归并为整场会议语义 Topic Map。

页面变化只作为证据，不直接生成 Topic。长会议先按约 15 分钟处理窗口做局部归纳，
再从全场视角归并成 3–8 个一级论点；每个节点必须携带可验证的 T/P/C ID。
stdout 只输出窗口数、节点数、耗时等元数据，不打印会议正文或模型输出。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import meeting_artifact as artifact
import meeting_structure
from meeting_core.llm import validated_api_base


SCHEMA = "meeting-topic-map/v3"
# v1/v2 旧图 revisions 匹配时仍可读；v3 将导航归属与代表证据分层。
LEGACY_SCHEMAS = frozenset({"meeting-topic-map/v1", "meeting-topic-map/v2"})
ACCEPTED_SCHEMAS = LEGACY_SCHEMAS | {SCHEMA}
ROUTER = validated_api_base(os.environ.get(
    "MEETING_LLM_API", "http://127.0.0.1:11435/v1")) + "/chat/completions"
MODEL = os.environ.get("MEETING_LLM_MODEL", "qwen3.6-35b-a3b-operator")
ALLOWED_CHILD_TYPES = {
    "context", "argument", "counterpoint", "decision", "action",
    "open_question", "risk", "evidence", "discussion",
}

CHUNK_PROMPT = """你负责整理一段会议的局部语义，不要按截图或页面变化分章。
输入是 meeting-topic-chunk-input/v1 JSON。请识别这一时间窗真正讨论的 1–5 个候选论点，
保留观点、分歧、决定、行动和未决问题的区别。页面标题只能辅助理解，不能单独证明决定。
保持紧凑：summary 不超过 120 个汉字，每个候选 title 不超过 30 个汉字、summary 不超过
160 个汉字；只列引用 ID，不复制逐字稿原文。

覆盖要求：本窗口的每个 turn 都必须有去向。有讨论内容的归入某个候选论点的 turn_ids；
确实不构成讨论内容的（如寒暄、等待、调试设备、纯翻页展示）列入 uncovered_turn_ids，
并用 uncovered_reason 一句话说明。没有本窗口 turn 支撑的候选论点不要输出。

只输出 JSON：
{{"summary":"本段推进", "uncovered_turn_ids":["T..."], "uncovered_reason":"可选说明",
 "candidate_topics":[
  {{"title":"候选论点", "summary":"本段如何推进它", "turn_ids":["T..."],
   "claim_ids":["C..."], "page_ids":["P..."]}}
]}}

所有 ID 必须来自输入。输入：
{context}
"""

REDUCE_PROMPT = """你负责生成整场会议的逻辑思维导图，而不是时间轴或截屏目录。
输入是 meeting-topic-reduce-input/v1：包含各大时间窗的局部归纳和权威 evidence claims。

请从全场视角归并为 3–8 个一级论点。相同论点即使在不连续时间再次出现，也必须合并为
同一个 topic，并保留多个证据范围。每个 topic 下用 2–7 个结构化子节点说明背景、主要观点、
反方/约束、决定、行动、风险或未决问题。不要把页面、时间窗或说话人直接当成论点。
决定/行动状态必须服从输入 claim，页面展示不能被升级为会议结论。
保持紧凑：meeting_summary 不超过 120 个汉字；topic title 不超过 30 个汉字、summary 不超过
220 个汉字；child title 不超过 30 个汉字、summary 不超过 140 个汉字。只列引用 ID，不复制
逐字稿或 claim 原文，不输出重复节点。
覆盖要求：一级论点必须用 candidate_ids 列出它吸收的所有局部候选；每个 candidate_id
必须恰好出现在一个一级论点中，不得整窗丢弃。turn_ids/claim_ids 仍只选真正有代表性的论据，
不要为了导航覆盖而把所有 turn_ids 复制进 topic。窗口的 uncovered_turn_ids 不得创建 Topic，
它们会由代码标为 transition；只有局部候选本身就是弱价值内容时，才可吸收到至多一个
“过渡与杂项”类论点，并为该论点携带 "low_value": true。

只输出 JSON：
{{"meeting_summary":"一句话说明整场推进", "topics":[
  {{"title":"一级论点", "summary":"该论点如何展开及当前结果", "candidate_ids":["W001C01"],
   "turn_ids":["T..."], "claim_ids":["C..."], "page_ids":["P..."],
   "children":[
     {{"type":"context|argument|counterpoint|decision|action|open_question|risk|evidence|discussion",
      "title":"子节点标题", "summary":"内容", "turn_ids":["T..."],
      "claim_ids":["C..."], "page_ids":["P..."]}}
   ]}}
]}}

所有 ID 必须来自输入。不要输出 Markdown、解释或思考过程。输入：
{context}
"""


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _minutes_path(mdir: Path) -> Path | None:
    return next((mdir / name for name in ("minutes.md", "minutes.spk.md")
                 if (mdir / name).is_file()), None)


def current_revisions(mdir: Path) -> dict:
    minutes = _minutes_path(mdir)
    return {
        "transcript": artifact.file_revision(mdir / "transcript.spk.json"),
        "minutes": artifact.file_revision(minutes) if minutes else None,
        "slides": artifact.file_revision(mdir / "slides.json"),
        "page_descriptions": artifact.file_revision(mdir / "page_desc.json"),
    }


def load_current_topic_map(mdir: Path) -> tuple[str, dict]:
    """返回 (ready|stale|missing, map)。v1/v2 均接受,revisions 匹配即 ready;stale 不暴露旧节点。"""
    path = Path(mdir) / "meeting.topic-map.json"
    if not path.is_file():
        return "missing", {}
    value = _read_json(path, {})
    if (value.get("schema") not in ACCEPTED_SCHEMAS
            or value.get("revisions") != current_revisions(Path(mdir))):
        return "stale", {}
    if value.get("schema") == SCHEMA:
        value = _normalize_v3_navigation(value)
    return "ready", value


def _default_llm(prompt: str, max_tokens: int) -> str:
    body = json.dumps({
        "model": MODEL,
        "temperature": 0.15,
        "max_tokens": max_tokens,
        # llama.cpp 的 OpenAI-compatible grammar 约束只保证 JSON 语法；字段、引用 ID 与
        # 主归属仍由下方 schema/sanitizer 校验。相比“自由文本后再让 LLM 修 JSON”，它能
        # 直接消除引号/尾逗号/截断前的格式漂移，并显著减少真实长会议的修复轮。
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": prompt}],
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        ROUTER, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=1800) as response:
        data = json.loads(response.read())
    return meeting_structure.clean_reasoning_text(
        data["choices"][0]["message"].get("content", ""))


def _model_json(value) -> dict:
    if isinstance(value, dict):
        return value
    # JSON 不能经过面向 VL 展示文案的 clean_model_text：后者会删除独占一行的 `{`/`}`
    # 和拆 LaTeX 包装。这里只剥 reasoning/special tokens，完整保留数据语法。
    text = meeting_structure.clean_reasoning_text(str(value or ""))
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.I | re.S)
    candidate = fenced.group(1) if fenced else text[text.find("{"):text.rfind("}") + 1]
    if not candidate:
        raise ValueError("模型未返回 JSON 对象")
    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise ValueError("Topic Map 输出必须是 JSON 对象")
    return parsed


def _repair_model_json(call: Callable[[str, int], object], value, *,
                       max_tokens: int = 7000) -> dict:
    """只修 JSON 语法；局部 map 与最终 reduce 共用，避免单窗失败丢掉整场结果。"""
    repair_prompt = (
        "你是严格的 JSON 格式修复器。修复下面对象中的缺逗号、未转义引号、括号和尾逗号；"
        "不得改写、增删或重新归纳任何字段值、T/P/C ID、topic、candidate_topic 或 child。"
        "只输出一个合法 JSON 对象，不要 Markdown 或解释。待修复文本：\n" + str(value))
    return _model_json(call(repair_prompt, max_tokens))


def _annotate_candidates(summaries: list[dict]) -> None:
    """给局部候选补稳定 ID，供 reduce 明确声明语义归并关系。

    旧 checkpoint 没有 candidate_id 时也按窗口/顺序确定性补齐；模型手写的
    ID 不作权威值，避免重复或跨窗口引用。
    """
    for window_index, window in enumerate(summaries, 1):
        for candidate_index, candidate in enumerate(window.get("candidate_topics") or [], 1):
            if isinstance(candidate, dict):
                candidate["candidate_id"] = f"W{window_index:03d}C{candidate_index:02d}"


def _fallback_reduce(summaries: list[dict]) -> dict:
    """最终归并连续输出坏 JSON 时，直接投影局部候选，避免整场脉络消失。

    这条路径不重新解释逐字稿：标题、摘要和 T/P/C 引用只取已经通过局部归纳的
    candidate_topics。完全相同的标题跨窗口合并；超过八组时把余项聚到最后一组，
    保证引用不丢。局部归纳本身不足三个主题时，结果仍交给既有质量门槛处理，
    不为了凑数伪造主题。
    """
    groups: list[dict] = []
    by_title: dict[str, dict] = {}
    def extend_unique(target: list, values) -> None:
        target.extend(value for value in (values or []) if value and value not in target)

    for window in summaries:
        for candidate in window.get("candidate_topics") or []:
            if not isinstance(candidate, dict):
                continue
            title = _plain(candidate.get("title"), 100)
            if not title:
                continue
            key = re.sub(r"[^\w\u3400-\u9fff]+", "", title).casefold()
            group = by_title.get(key)
            if group is None:
                group = {
                    "title": title,
                    "summary_parts": [],
                    "turn_ids": [], "claim_ids": [], "page_ids": [],
                    "candidate_ids": [],
                    "children": [],
                }
                by_title[key] = group
                groups.append(group)
            summary = _plain(candidate.get("summary"), 360)
            if summary and summary not in group["summary_parts"]:
                group["summary_parts"].append(summary)
            for field in ("turn_ids", "claim_ids", "page_ids"):
                extend_unique(group[field], candidate.get(field))
            extend_unique(group["candidate_ids"], [candidate.get("candidate_id")])
            group["children"].append({
                "type": "discussion", "title": title,
                "summary": summary,
                "turn_ids": list(candidate.get("turn_ids") or []),
                "claim_ids": list(candidate.get("claim_ids") or []),
                "page_ids": list(candidate.get("page_ids") or []),
            })

    if len(groups) > 8:
        overflow = groups[8:]
        groups = groups[:8]
        target = groups[-1]
        for group in overflow:
            extend_unique(target["summary_parts"], group["summary_parts"])
            for field in ("turn_ids", "claim_ids", "page_ids", "candidate_ids", "children"):
                extend_unique(target[field], group[field])

    topics = []
    for group in groups:
        topics.append({
            "title": group["title"],
            "summary": " ".join(group["summary_parts"])[:500],
            "turn_ids": group["turn_ids"],
            "claim_ids": group["claim_ids"],
            "page_ids": group["page_ids"],
            "candidate_ids": group["candidate_ids"],
            "children": group["children"][:7],
            "low_value": bool(group.get("low_value")),
        })
    if not topics:
        raise ValueError("局部归纳也没有可用于兜底的候选主题")
    meeting_summary = " ".join(
        part for part in (_plain(item.get("summary"), 240) for item in summaries) if part)
    return {
        "meeting_summary": meeting_summary[:600],
        "topics": topics,
        "_deterministic_fallback": True,
    }


def _expand_candidate_refs(raw: dict, summaries: list[dict]) -> dict:
    """让整场议题继承已匹配局部候选的完整引用，而不是只保留 reduce 代表样本。

    只有候选与最终议题至少共享一个 turn 才扩展，因此沿用的是模型已有语义映射，
    不是按时间邻近猜测归属。
    """
    topics = [topic for topic in (raw.get("topics") or []) if isinstance(topic, dict)]
    recovered: set[str] = set()
    if not topics:
        return raw

    def topic_turns(topic: dict) -> set[str]:
        values = set(topic.get("turn_ids") or [])
        for child in topic.get("children") or []:
            if isinstance(child, dict):
                values.update(child.get("turn_ids") or [])
        return values

    for window in summaries:
        for candidate in window.get("candidate_topics") or []:
            if not isinstance(candidate, dict):
                continue
            candidate_turns = list(dict.fromkeys(candidate.get("turn_ids") or []))
            if not candidate_turns:
                continue
            candidate_set = set(candidate_turns)
            scores = [len(candidate_set.intersection(topic_turns(topic))) for topic in topics]
            best_score = max(scores, default=0)
            # 一个候选同时锚到多个最终 Topic 且没有唯一最佳项，说明 reduce 对它做了拆分；
            # 此时不能把整段引用强塞给任一边。
            if best_score <= 0 or scores.count(best_score) != 1:
                continue
            target = topics[scores.index(best_score)]
            before = set(target.get("turn_ids") or [])
            target["turn_ids"] = list(dict.fromkeys(
                list(target.get("turn_ids") or []) + candidate_turns))
            inherited = list(candidate_set - before)
            target["_inherited_turn_ids"] = list(dict.fromkeys(
                list(target.get("_inherited_turn_ids") or []) + inherited))
            recovered.update(inherited)
            for key in ("claim_ids", "page_ids"):
                target[key] = list(dict.fromkeys(
                    list(target.get(key) or []) + list(candidate.get(key) or [])))
    raw["_candidate_turns_recovered"] = len(recovered)
    return raw


def _turn_windows(turns: list[dict], chunk_seconds: float, max_chars: int = 16000) -> list[list[dict]]:
    windows: list[list[dict]] = []
    current: list[dict] = []
    chars, start = 0, 0.0
    for turn in turns:
        turn_start = float(turn.get("start", 0))
        text_len = len(str(turn.get("text") or ""))
        if current and ((turn_start - start >= chunk_seconds)
                        or chars + text_len > max_chars):
            windows.append(current)
            current, chars, start = [], 0, turn_start
        if not current:
            start = turn_start
        current.append(turn)
        chars += text_len
    if current:
        windows.append(current)
    return windows


def _clean_ids(values, allowed: set[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in (values or []) if str(value) in allowed))


def _plain(value, limit: int) -> str:
    text = meeting_structure.clean_model_text(str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _merge_ranges(ranges: list[list[float]], gap: float = 60.0) -> list[list[float]]:
    ordered = sorted(([float(start), float(end)] for start, end in ranges if end >= start),
                     key=lambda item: (item[0], item[1]))
    merged: list[list[float]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1] + gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([round(start, 3), round(end, 3)])
    return merged


def _segment_interval(segment: dict) -> tuple[float, float]:
    ranges = segment.get("ranges") or []
    if ranges:
        return float(ranges[0][0]), float(ranges[-1][1])
    return float(segment.get("start") or 0), float(segment.get("end") or 0)


def _set_segment_interval(segment: dict, start: float, end: float) -> None:
    start, end = round(float(start), 3), round(max(float(start), float(end)), 3)
    segment["ranges"] = [[start, end]]
    segment["start"], segment["end"] = start, end


def _coalesce_navigation_segments(segments: list[dict],
                                  max_interrupt_seconds: float = 60.0) -> list[dict]:
    """把同一 Topic 之间的短回应直接归回章节，并修正重复时间戳重叠。

    Topic Map 的时间线是章节导航，不是逐轮分类可视化。短 transition/unclassified
    被同一 topic 前后夹住时，保留它们的 turn_ids，但不再把章节切碎。不同 topic
    或超过阈值的间隔仍保持独立。
    """
    source = []
    for segment in segments:
        item = dict(segment)
        item["turn_ids"] = list(segment.get("turn_ids") or [])
        item["ranges"] = [list(value) for value in segment.get("ranges") or []]
        source.append(item)

    output: list[dict] = []
    index = 0
    while index < len(source):
        current = source[index]
        if current.get("kind") != "topic" or not current.get("topic_id"):
            output.append(current)
            index += 1
            continue
        merged = current
        cursor = index
        while cursor + 1 < len(source):
            next_topic_index = cursor + 1
            while (next_topic_index < len(source)
                   and source[next_topic_index].get("kind") != "topic"):
                next_topic_index += 1
            if next_topic_index >= len(source):
                break
            next_topic = source[next_topic_index]
            if next_topic.get("topic_id") != merged.get("topic_id"):
                break
            _, merged_end = _segment_interval(merged)
            next_start, next_end = _segment_interval(next_topic)
            if max(0.0, next_start - merged_end) > max_interrupt_seconds:
                break
            for bridge in source[cursor + 1:next_topic_index + 1]:
                merged["turn_ids"].extend(
                    turn_id for turn_id in bridge.get("turn_ids") or []
                    if turn_id not in merged["turn_ids"])
            merged_start, _ = _segment_interval(merged)
            _set_segment_interval(merged, merged_start, max(merged_end, next_end))
            cursor = next_topic_index
        output.append(merged)
        index = cursor + 1

    # Teams DOCX 可能给连续发言同一个粗粒度时间戳。章节序列仍应互斥；按顺序在
    # 重叠区间中点切开，只调整导航投影，不改 canonical 逐字稿时间。
    for index in range(1, len(output)):
        previous, current = output[index - 1], output[index]
        previous_start, previous_end = _segment_interval(previous)
        current_start, current_end = _segment_interval(current)
        if current_start >= previous_end:
            continue
        overlap_end = min(previous_end, current_end)
        boundary = (current_start + overlap_end) / 2.0
        _set_segment_interval(previous, previous_start, boundary)
        _set_segment_interval(current, boundary, current_end)

    for index, segment in enumerate(output, 1):
        segment["id"] = f"S{index:03d}"
    return output


def _normalize_v3_navigation(value: dict) -> dict:
    """读取存量 v3 时确定性收敛章节，不要求重新调用 LLM。"""
    output = dict(value)
    segments = _coalesce_navigation_segments(value.get("navigation_segments") or [])
    if not segments:
        return output
    topics = [dict(topic) for topic in value.get("topics") or []]
    for topic in topics:
        topic_id = str(topic.get("id") or "")
        owned = [segment for segment in segments
                 if segment.get("kind") == "topic" and segment.get("topic_id") == topic_id]
        topic["navigation_turn_ids"] = list(dict.fromkeys(
            turn_id for segment in owned for turn_id in segment.get("turn_ids") or []))
        ranges = [list(segment["ranges"][0]) for segment in owned if segment.get("ranges")]
        topic["ranges"] = ranges or list(topic.get("evidence_ranges") or topic.get("ranges") or [])
        topic["start"] = topic["ranges"][0][0] if topic["ranges"] else None
        topic["end"] = topic["ranges"][-1][1] if topic["ranges"] else None

    all_turns = {turn_id for segment in segments for turn_id in segment.get("turn_ids") or []}
    semantic_turns = {turn_id for segment in segments if segment.get("kind") == "topic"
                      for turn_id in segment.get("turn_ids") or []}
    transition_turns = {turn_id for segment in segments if segment.get("kind") == "transition"
                        for turn_id in segment.get("turn_ids") or []}
    unclassified_turns = all_turns - semantic_turns - transition_turns
    evidence_turns = {turn_id for topic in topics for turn_id in topic.get("turn_ids") or []}
    stats = dict(value.get("stats") or {})
    count = len(all_turns)
    stats.update({
        "coverage": round(len(semantic_turns) / count, 4) if count else 0.0,
        "turn_coverage": round(len(semantic_turns) / count, 4) if count else 0.0,
        "navigation_coverage": round(
            (len(semantic_turns) + len(transition_turns)) / count, 4) if count else 0.0,
        "evidence_turn_coverage": round(len(evidence_turns) / count, 4) if count else 0.0,
        "unassigned_turns": len(unclassified_turns),
        "transition_turns": len(transition_turns),
        "candidate_turns_recovered": len(semantic_turns - evidence_turns),
    })
    starts = [start for segment in segments for start, _ in segment.get("ranges") or []]
    ends = [end for segment in segments for _, end in segment.get("ranges") or []]
    topic_seconds = sum(end - start for start, end in _merge_ranges(
        [bounds for segment in segments if segment.get("kind") == "topic"
         for bounds in segment.get("ranges") or []], gap=0.0))
    duration = max(ends, default=0) - min(starts, default=0)
    stats["time_coverage"] = round(min(1.0, topic_seconds / duration), 4) if duration else 0.0
    output["topics"], output["navigation_segments"], output["stats"] = topics, segments, stats
    return output


def _smooth_short_interruptions(source_turns: list[dict],
                                turn_owner: dict[str, tuple[str, str | None]],
                                max_interrupt_seconds: float = 60.0) -> None:
    """生成阶段直接把同一议题之间的短非议题轮次归回该议题。"""
    index = 0
    while index < len(source_turns):
        turn_id = str(source_turns[index].get("id"))
        if turn_owner[turn_id][0] == "topic":
            index += 1
            continue
        start = index
        while index < len(source_turns):
            current_id = str(source_turns[index].get("id"))
            if turn_owner[current_id][0] == "topic":
                break
            index += 1
        if start == 0 or index >= len(source_turns):
            continue
        before_id = str(source_turns[start - 1].get("id"))
        after_id = str(source_turns[index].get("id"))
        before_owner, after_owner = turn_owner[before_id], turn_owner[after_id]
        if before_owner[0] != "topic" or before_owner != after_owner:
            continue
        before_end = float(source_turns[start - 1].get("end", 0))
        after_start = float(source_turns[index].get("start", 0))
        if max(0.0, after_start - before_end) > max_interrupt_seconds:
            continue
        for turn in source_turns[start:index]:
            turn_owner[str(turn.get("id"))] = before_owner


def _apply_navigation(topics: list[dict], summaries: list[dict],
                      source_turns: list[dict]) -> tuple[list[dict], dict]:
    """把局部候选投影为全量导航，不污染代表证据。

    topic.turn_ids 继续表示可审计的代表论据；navigation_turn_ids/ranges
    负责播放器和时间轴的连续浏览。局部模型明确标为寒暄/等待的
    uncovered 轮次写为 transition；其他没有语义归属的轮次必须显式写为
    unclassified，不得按时间邻近伪造覆盖。
    """
    valid_turns = {str(turn.get("id")) for turn in source_turns}
    turn_by_id = {str(turn.get("id")): turn for turn in source_turns}
    topic_by_id = {str(topic.get("id")): topic for topic in topics}
    candidates: dict[str, dict] = {}
    explicit_low_value: set[str] = set()
    for window in summaries:
        explicit_low_value.update(_clean_ids(window.get("uncovered_turn_ids"), valid_turns))
        for candidate in window.get("candidate_topics") or []:
            if not isinstance(candidate, dict):
                continue
            candidate_id = str(candidate.get("candidate_id") or "")
            if not candidate_id:
                continue
            candidates[candidate_id] = {
                **candidate,
                "turn_ids": _clean_ids(candidate.get("turn_ids"), valid_turns),
            }

    # reduce 显式返回 candidate_ids 是主路径；存量/模型漏字段时，只在
    # 局部候选与某个终稿论点共享唯一最强代表 turn 时补建映射。
    candidate_owner: dict[str, str] = {}
    duplicate_candidate_assignments = 0
    for topic in topics:
        topic_id = str(topic.get("id"))
        cleaned = []
        for candidate_id in topic.get("candidate_ids") or []:
            candidate_id = str(candidate_id)
            if candidate_id not in candidates:
                continue
            if candidate_id in candidate_owner:
                duplicate_candidate_assignments += 1
                continue
            candidate_owner[candidate_id] = topic_id
            cleaned.append(candidate_id)
        topic["candidate_ids"] = cleaned

    evidence_sets = {str(topic.get("id")): set(topic.get("turn_ids") or []) for topic in topics}
    for candidate_id, candidate in candidates.items():
        if candidate_id in candidate_owner:
            continue
        candidate_turns = set(candidate.get("turn_ids") or [])
        scores = [len(candidate_turns.intersection(evidence_sets[str(topic.get("id"))]))
                  for topic in topics]
        best = max(scores, default=0)
        if best <= 0 or scores.count(best) != 1:
            continue
        topic = topics[scores.index(best)]
        topic_id = str(topic.get("id"))
        candidate_owner[candidate_id] = topic_id
        topic["candidate_ids"].append(candidate_id)

    # 终稿代表论据对它自己的轮次具有最高主归属优先级；候选覆盖只补其余轮次。
    turn_owner: dict[str, tuple[str, str | None]] = {}
    for topic in topics:
        topic_id = str(topic.get("id"))
        for turn_id in topic.get("turn_ids") or []:
            if turn_id in valid_turns:
                turn_owner.setdefault(turn_id, ("topic", topic_id))
    for candidate_id, topic_id in candidate_owner.items():
        for turn_id in candidates[candidate_id].get("turn_ids") or []:
            turn_owner.setdefault(turn_id, ("topic", topic_id))
    for turn_id in explicit_low_value:
        turn_owner.setdefault(turn_id, ("transition", None))
    for turn_id in valid_turns:
        turn_owner.setdefault(turn_id, ("unclassified", None))

    _smooth_short_interruptions(source_turns, turn_owner)

    topic_navigation: dict[str, list[str]] = {topic_id: [] for topic_id in topic_by_id}
    transition_turns: list[str] = []
    unclassified_turns: list[str] = []
    for turn in source_turns:
        turn_id = str(turn.get("id"))
        kind, topic_id = turn_owner[turn_id]
        if kind == "topic" and topic_id in topic_navigation:
            topic_navigation[topic_id].append(turn_id)
        elif kind == "transition":
            transition_turns.append(turn_id)
        else:
            unclassified_turns.append(turn_id)

    for topic in topics:
        topic_id = str(topic.get("id"))
        topic["evidence_ranges"] = list(topic.get("ranges") or [])
        topic["navigation_turn_ids"] = topic_navigation[topic_id]

    segments: list[dict] = []
    current: list[dict] = []
    current_owner: tuple[str, str | None] | None = None

    def flush_segment() -> None:
        nonlocal current
        if not current or current_owner is None:
            return
        kind, topic_id = current_owner
        # 同一语义连续段只画一个可点击区间；段内短暂停顿仍属于同一讨论，
        # 但超过 60 秒的空白会在下方循环中主动切段，避免跨大段静音拉成长条。
        ranges = [[round(float(current[0].get("start", 0)), 3),
                   round(float(current[-1].get("end", 0)), 3)]]
        segments.append({
            "id": f"S{len(segments) + 1:03d}",
            "kind": kind,
            "topic_id": topic_id,
            "turn_ids": [str(item.get("id")) for item in current],
            "ranges": ranges,
            "start": ranges[0][0] if ranges else None,
            "end": ranges[-1][1] if ranges else None,
        })
        current = []

    for turn in source_turns:
        owner = turn_owner[str(turn.get("id"))]
        long_pause = bool(current) and float(turn.get("start", 0)) > (
            float(current[-1].get("end", 0)) + 60.0)
        if current_owner != owner or long_pause:
            flush_segment()
            current_owner = owner
        current.append(turn)
    flush_segment()
    segments = _coalesce_navigation_segments(segments)

    # Topic 的 ranges 用互斥导航段生成，不能再按同一 topic 的邻近时间合并；
    # 否则 topic A 离开后短暂切到 transition/topic B，再回来时会发生视觉覆盖。
    for topic in topics:
        topic_id = str(topic.get("id"))
        navigation_ranges = [list(segment["ranges"][0]) for segment in segments
                             if segment["kind"] == "topic"
                             and segment.get("topic_id") == topic_id
                             and segment.get("ranges")]
        topic["ranges"] = navigation_ranges or topic["evidence_ranges"]
        topic["start"] = topic["ranges"][0][0] if topic["ranges"] else None
        topic["end"] = topic["ranges"][-1][1] if topic["ranges"] else None

    semantic_turns = {turn_id for values in topic_navigation.values() for turn_id in values}
    evidence_turns = {turn_id for topic in topics for turn_id in topic.get("turn_ids") or []}
    exact_ranges = _merge_ranges([
        [turn_by_id[turn_id].get("start", 0), turn_by_id[turn_id].get("end", 0)]
        for turn_id in semantic_turns
    ], gap=0.0)
    semantic_seconds = sum(end - start for start, end in exact_ranges)
    meeting_start = min((float(turn.get("start", 0)) for turn in source_turns), default=0.0)
    meeting_end = max((float(turn.get("end", 0)) for turn in source_turns), default=0.0)
    duration = max(0.0, meeting_end - meeting_start)
    count = len(source_turns)
    topic_turn_coverage = round(len(semantic_turns) / count, 4) if count else 0.0
    classified_count = len(semantic_turns) + len(transition_turns)
    stats = {
        # v3 的 coverage 以导航轮次为分母，不再用会议时长惩罚正常停顿；
        # 精确发言时间比例另存 time_coverage。
        "coverage": topic_turn_coverage,
        "turn_coverage": topic_turn_coverage,
        "time_coverage": round(min(1.0, semantic_seconds / duration), 4) if duration else 0.0,
        "navigation_coverage": round(classified_count / count, 4) if count else 0.0,
        "evidence_turn_coverage": round(len(evidence_turns) / count, 4) if count else 0.0,
        "unassigned_turns": len(unclassified_turns),
        "transition_turns": len(transition_turns),
        "unmapped_candidates": len(candidates) - len(candidate_owner),
        "duplicate_candidate_assignments": duplicate_candidate_assignments,
        "candidate_turns_recovered": len(semantic_turns - evidence_turns),
    }
    return segments, stats


def _sanitize_map(raw: dict, evidence: dict, revisions: dict, *, model: str,
                  window_count: int, chunk_seconds: float,
                  summaries: list[dict] | None = None) -> dict:
    source_turns = evidence.get("sources", {}).get("transcript", [])
    source_pages = evidence.get("sources", {}).get("pages", [])
    claims = evidence.get("claims", [])
    turn_by_id = {item["id"]: item for item in source_turns}
    page_by_id = {item["id"]: item for item in source_pages}
    claim_by_id = {item["id"]: item for item in claims}
    valid_turns, valid_pages, valid_claims = set(turn_by_id), set(page_by_id), set(claim_by_id)

    def refs(node: dict) -> tuple[list[str], list[str], list[str]]:
        turn_ids = _clean_ids(node.get("turn_ids"), valid_turns)
        claim_ids = _clean_ids(node.get("claim_ids"), valid_claims)
        page_ids = _clean_ids(node.get("page_ids"), valid_pages)
        for claim_id in claim_ids:
            claim = claim_by_id[claim_id]
            turn_ids = list(dict.fromkeys(turn_ids + _clean_ids(claim.get("turn_ids"), valid_turns)))
            page_ids = list(dict.fromkeys(page_ids + _clean_ids(claim.get("page_ids"), valid_pages)))
        return turn_ids, claim_ids, page_ids

    def ranges_for(turn_ids: list[str], page_ids: list[str]) -> list[list[float]]:
        ranges = [[turn_by_id[item]["start"], turn_by_id[item]["end"]] for item in turn_ids]
        if not ranges:
            ranges = [bounds for item in page_ids for bounds in page_by_id[item].get("ranges", [])]
        return _merge_ranges(ranges)

    topics = []
    for raw_topic in list(raw.get("topics") or [])[:8]:
        if not isinstance(raw_topic, dict):
            continue
        # 结论引用可能横跨相邻议题。先记住模型显式给每个议题/子节点分配的轮次，后续去重时
        # 让显式分配优先于 claim 展开的间接轮次；否则前一议题的一条跨段 claim 会吞掉后一
        # 议题唯一的锚点，导致整个节点消失。
        inherited_turns = set(_clean_ids(raw_topic.get("_inherited_turn_ids"), valid_turns))
        explicit_turns = [turn_id for turn_id in _clean_ids(
            raw_topic.get("turn_ids"), valid_turns) if turn_id not in inherited_turns]
        topic_turns, topic_claims, topic_pages = refs(raw_topic)
        children = []
        for raw_child in list(raw_topic.get("children") or [])[:8]:
            if not isinstance(raw_child, dict):
                continue
            explicit_turns = list(dict.fromkeys(
                explicit_turns + _clean_ids(raw_child.get("turn_ids"), valid_turns)))
            child_turns, child_claims, child_pages = refs(raw_child)
            if not (child_turns or child_claims or child_pages):
                continue
            child_type = str(raw_child.get("type") or "discussion")
            if child_type not in ALLOWED_CHILD_TYPES:
                child_type = "discussion"
            if child_type == "action" and not any(
                    claim_by_id[item].get("formal_action") for item in child_claims):
                child_type = "discussion"
            children.append({
                "id": "", "type": child_type,
                "title": _plain(raw_child.get("title"), 80) or "讨论要点",
                "summary": _plain(raw_child.get("summary"), 360),
                "turn_ids": child_turns, "claim_ids": child_claims, "page_ids": child_pages,
                "ranges": ranges_for(child_turns, child_pages),
            })
            topic_turns = list(dict.fromkeys(topic_turns + child_turns))
            topic_claims = list(dict.fromkeys(topic_claims + child_claims))
            topic_pages = list(dict.fromkeys(topic_pages + child_pages))
        if not (topic_turns or topic_claims or topic_pages):
            continue
        if not children:
            children.append({
                "id": "", "type": "discussion", "title": "主要讨论",
                "summary": _plain(raw_topic.get("summary"), 360),
                "turn_ids": topic_turns, "claim_ids": topic_claims, "page_ids": topic_pages,
                "ranges": ranges_for(topic_turns, topic_pages),
            })
        topic_id = f"M{len(topics) + 1:02d}"
        for index, child in enumerate(children, 1):
            child["id"] = f"{topic_id}-{index:02d}"
        topic_ranges = ranges_for(topic_turns, topic_pages)
        topics.append({
            "id": topic_id,
            "title": _plain(raw_topic.get("title"), 100) or f"论点 {len(topics) + 1}",
            "summary": _plain(raw_topic.get("summary"), 500),
            "low_value": bool(raw_topic.get("low_value")),
            "candidate_ids": list(dict.fromkeys(
                str(item) for item in (raw_topic.get("candidate_ids") or []) if item)),
            "_explicit_turn_ids": explicit_turns,
            "turn_ids": topic_turns, "claim_ids": topic_claims, "page_ids": topic_pages,
            "ranges": topic_ranges,
            "start": topic_ranges[0][0] if topic_ranges else None,
            "end": topic_ranges[-1][1] if topic_ranges else None,
            "children": children,
        })
    if not topics:
        raise ValueError("模型没有生成带有效证据的 Topic")

    # 一级议题是整场阅读与时间轴的“主归属”，同一轮次/结论不能同时铺进多个一级议题。
    # 模型仍可通过摘要表达关联，但时间引用由首次出现的一级议题持有，避免两个长条互相覆盖。
    owned_turns: set[str] = set()
    owned_claims: set[str] = set()
    overlap_turns_removed = 0
    primary_topics = []
    preferred_turn_owner: dict[str, int] = {}
    for topic_index, topic in enumerate(topics):
        for turn_id in topic.pop("_explicit_turn_ids", []):
            preferred_turn_owner.setdefault(turn_id, topic_index)
    for topic_index, topic in enumerate(topics):
        topic_turns = [
            item for item in topic["turn_ids"]
            if item not in owned_turns
            and preferred_turn_owner.get(item, topic_index) == topic_index
        ]
        overlap_turns_removed += len(topic["turn_ids"]) - len(topic_turns)
        topic_claims = [item for item in topic["claim_ids"] if item not in owned_claims]
        if not topic_turns:
            continue
        owned_turns.update(topic_turns)
        owned_claims.update(topic_claims)
        topic_turn_set, topic_claim_set = set(topic_turns), set(topic_claims)
        children = []
        for child in topic["children"]:
            child_turns = [item for item in child["turn_ids"] if item in topic_turn_set]
            child_claims = [item for item in child["claim_ids"] if item in topic_claim_set]
            if not (child_turns or child_claims):
                continue
            child = dict(child, turn_ids=child_turns, claim_ids=child_claims,
                         ranges=ranges_for(child_turns, child.get("page_ids", [])))
            children.append(child)
        if not children:
            children = [{
                "id": "", "type": "discussion", "title": "主要讨论",
                "summary": topic["summary"], "turn_ids": topic_turns,
                "claim_ids": topic_claims, "page_ids": topic["page_ids"],
                "ranges": ranges_for(topic_turns, topic["page_ids"]),
            }]
        topic_ranges = ranges_for(topic_turns, topic["page_ids"])
        primary_topics.append(dict(
            topic, turn_ids=topic_turns, claim_ids=topic_claims, children=children,
            ranges=topic_ranges,
            start=topic_ranges[0][0] if topic_ranges else None,
            end=topic_ranges[-1][1] if topic_ranges else None,
        ))
    topics = primary_topics
    for topic_index, topic in enumerate(topics, 1):
        topic["id"] = topic_id = f"M{topic_index:02d}"
        for child_index, child in enumerate(topic["children"], 1):
            child["id"] = f"{topic_id}-{child_index:02d}"
    if not topics:
        raise ValueError("一级议题去重后没有可用的逐字稿依据")

    navigation_segments, navigation_stats = _apply_navigation(
        topics, summaries or [], source_turns)
    return {
        "schema": SCHEMA,
        "state": "ready",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "revisions": revisions,
        "generation": {"model": model,
                       "strategy": ("map-reduce/local-candidates-fallback-v3"
                                    if raw.get("_deterministic_fallback") else
                                    "map-reduce/compact-recovery-v2"
                                    if raw.get("_compact_recovery") else "map-reduce/v1"),
                       "chunk_seconds": chunk_seconds, "window_count": window_count},
        "meeting_summary": _plain(raw.get("meeting_summary"), 600),
        "topics": topics,
        "navigation_segments": navigation_segments,
        "stats": {"topics": len(topics),
                  "children": sum(len(topic["children"]) for topic in topics),
                  "overlap_turns_removed": overlap_turns_removed,
                  **navigation_stats},
    }


def generate_topic_map(mdir: Path, *, llm: Callable[[str, int], object] | None = None,
                       model: str = MODEL, chunk_seconds: float = 900.0) -> tuple[Path, dict]:
    mdir = Path(mdir).resolve()
    minutes_path = _minutes_path(mdir)
    transcript_path = mdir / "transcript.spk.json"
    if minutes_path is None or not transcript_path.is_file():
        raise ValueError("会议缺少纪要或具名逐字稿")
    turns = _read_json(transcript_path, [])
    if not turns:
        raise ValueError("逐字稿为空")
    pages = [item for item in _read_json(mdir / "slides.json", [])
             if item.get("kind", "slide") == "slide" and item.get("page") is not None]
    raw_desc = _read_json(mdir / "page_desc.json", {}).get("desc", {})
    descs = {int(key): str(value) for key, value in raw_desc.items() if str(key).isdigit()}
    bank_dir = Path(os.environ.get("MEETING_WEB_BANK", mdir.parent.parent / "speaker_bank"))
    profiles = artifact.load_speaker_profiles(turns, bank_dir)
    minutes = minutes_path.read_text(encoding="utf-8")
    evidence = artifact.build_evidence_document(mdir, minutes, turns, pages, descs, profiles,
                                                generation={"topic_map_input": True})
    structure = meeting_structure.build_structure(
        minutes, turns, pages, descs, evidence,
        duration=max((float(turn.get("end", 0)) for turn in turns), default=0))
    visual_titles = {item["id"]: item["title"] for item in structure.get("visuals", [])}
    source_turns = evidence["sources"]["transcript"]
    claims = evidence.get("claims", [])
    windows = _turn_windows(source_turns, chunk_seconds)
    call = llm or _default_llm
    revisions = current_revisions(mdir)
    checkpoint_path = mdir / ".topic-map-work.json"
    checkpoint = _read_json(checkpoint_path, {})
    checkpoint_valid = (
        checkpoint.get("schema") == "meeting-topic-map-work/v1"
        and checkpoint.get("revisions") == revisions
        and checkpoint.get("model") == model
        and checkpoint.get("chunk_seconds") == chunk_seconds
        and len(checkpoint.get("summaries", [])) <= len(windows)
    )
    summaries = list(checkpoint.get("summaries", [])) if checkpoint_valid else []
    _annotate_candidates(summaries)
    if summaries:
        print(f"[meta] Topic Map 复用 {len(summaries)}/{len(windows)} 个局部归纳", flush=True)
    for index, window in enumerate(windows[len(summaries):], len(summaries) + 1):
        turn_ids = {item["id"] for item in window}
        linked_claims = [claim for claim in claims
                         if turn_ids.intersection(claim.get("turn_ids", []))]
        page_ids = list(dict.fromkeys(
            [item.get("page_id") for item in window if item.get("page_id")]
            + [pid for claim in linked_claims for pid in claim.get("page_ids", [])]))
        payload = {
            "schema": "meeting-topic-chunk-input/v1",
            "window": {"index": index, "start": window[0]["start"], "end": window[-1]["end"]},
            "turns": [{key: item.get(key) for key in ("id", "start", "end", "speaker", "text")}
                      for item in window],
            "claims": [{key: claim.get(key) for key in
                        ("id", "kind", "status", "text", "turn_ids", "page_ids")}
                       for claim in linked_claims],
            "visuals": [{"id": page_id, "title": visual_titles.get(page_id, "屏幕资料")}
                        for page_id in page_ids],
        }
        prompt = CHUNK_PROMPT.format(context=json.dumps(payload, ensure_ascii=False,
                                                        separators=(",", ":")))
        # 真实 20 分钟纯音频会议在约 10 分钟窗口内就可能包含 5 个候选及大量 T 引用；
        # 2k 输出会在 JSON 尾部截断。保留充足余量，仍由 schema/sanitizer 控制节点数量。
        chunk_text = call(prompt, 3500)
        try:
            chunk_result = _model_json(chunk_text)
        except (json.JSONDecodeError, ValueError):
            print(f"[meta] Topic Map 局部归纳 {index}/{len(windows)} JSON 无效，正在修复格式",
                  flush=True)
            try:
                chunk_result = _repair_model_json(call, chunk_text, max_tokens=5000)
            except (json.JSONDecodeError, ValueError):
                # 单窗修复仍失败不再丢整场：空归纳交给 coverage 兜底做邻接分配。
                print(f"[warn] Topic Map 局部归纳 {index}/{len(windows)} 修复仍失败，"
                      "本窗按未覆盖处理", flush=True)
                chunk_result = {"summary": "", "candidate_topics": []}
        summaries.append(chunk_result)
        _annotate_candidates(summaries)
        checkpoint_value = {
            "schema": "meeting-topic-map-work/v1", "revisions": revisions,
            "model": model, "chunk_seconds": chunk_seconds, "summaries": summaries,
        }
        checkpoint_tmp = checkpoint_path.with_suffix(".tmp")
        checkpoint_tmp.write_text(json.dumps(checkpoint_value, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        checkpoint_tmp.replace(checkpoint_path)
        print(f"[meta] Topic Map 局部归纳 {index}/{len(windows)}", flush=True)
    reduce_payload = {
        "schema": "meeting-topic-reduce-input/v1",
        "windows": summaries,
        "claims": [{key: claim.get(key) for key in
                    ("id", "kind", "status", "text", "turn_ids", "page_ids")}
                   for claim in claims],
        "valid_ids": {
            "turn_ids": [item["id"] for item in source_turns],
            "claim_ids": [claim["id"] for claim in claims],
            "page_ids": [item["id"] for item in evidence["sources"]["pages"]],
        },
    }
    final_prompt = REDUCE_PROMPT.format(
        context=json.dumps(reduce_payload, ensure_ascii=False, separators=(",", ":")))
    reduce_text = call(final_prompt, 8000)
    try:
        raw = _model_json(reduce_text)
    except (json.JSONDecodeError, ValueError):
        # 只让本机模型修复上一次结果的语法，不重新归纳内容，也不打印原输出。
        print("[meta] Topic Map 全场归并 JSON 无效，正在修复输出格式", flush=True)
        try:
            raw = _repair_model_json(call, reduce_text, max_tokens=12000)
        except (json.JSONDecodeError, ValueError):
            # 修复仍失败（多为输出截断）：去掉 valid_ids 大列表和无关 claim 后做一次紧凑归并；
            # 比原样重放同一个超长 prompt 更可能得到完整 JSON。
            print("[meta] Topic Map 全场归并修复仍失败，改用紧凑输入重试一次", flush=True)
            referenced_claims = {
                claim_id for window in summaries for candidate in window.get("candidate_topics", [])
                if isinstance(candidate, dict) for claim_id in candidate.get("claim_ids", [])
            }
            compact_payload = {
                "schema": "meeting-topic-reduce-input/v1",
                "windows": summaries,
                "claims": [claim for claim in reduce_payload["claims"]
                           if claim.get("id") in referenced_claims],
            }
            compact_prompt = REDUCE_PROMPT.format(
                context=json.dumps(compact_payload, ensure_ascii=False, separators=(",", ":")))
            try:
                raw = _model_json(call(compact_prompt, 8000))
                raw["_compact_recovery"] = True
            except (json.JSONDecodeError, ValueError):
                print("[warn] Topic Map 全场归并重试仍无合法 JSON，"
                      "改用局部候选确定性组装", flush=True)
                raw = _fallback_reduce(summaries)
    result = _sanitize_map(raw, evidence, revisions, model=model,
                           window_count=len(windows), chunk_seconds=chunk_seconds,
                           summaries=summaries)
    path = mdir / "meeting.topic-map.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    checkpoint_path.unlink(missing_ok=True)
    return path, result


def generate_for_pipeline(mdir: Path) -> dict | None:
    """管线尾部 best-effort 生成；纪要成功时不因 Topic Map 单点失败而回滚。"""
    started = time.time()
    try:
        _path, result = generate_topic_map(mdir)
    except Exception as exc:
        print(f"[warn] Topic Map 暂未生成: {type(exc).__name__}: {exc}", flush=True)
        return None
    print(f"[meta] Topic Map: {result['stats']['topics']} 个论点 / "
          f"{result['stats']['children']} 个子节点 / "
          f"覆盖 {result['stats'].get('coverage', 0) * 100:.1f}% / "
          f"{result['generation']['window_count']} 个处理窗 / {time.time()-started:.1f}s", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="生成整场会议语义 Topic Map")
    parser.add_argument("meeting_dir", type=Path)
    parser.add_argument("--chunk-seconds", type=float, default=900.0)
    args = parser.parse_args()
    started = time.time()
    try:
        path, result = generate_topic_map(args.meeting_dir, chunk_seconds=args.chunk_seconds)
    except Exception as exc:
        print(f"[error] Topic Map 生成失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"[meta] Topic Map: {result['stats']['topics']} 个论点 / "
          f"{result['stats']['children']} 个子节点 / "
          f"覆盖 {result['stats'].get('coverage', 0) * 100:.1f}% / "
          f"{result['generation']['window_count']} 个处理窗 / {time.time()-started:.1f}s", flush=True)
    print(f"[meta] Topic Map 输出: {path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
