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


SCHEMA = "meeting-topic-map/v2"
# v1 旧图 revisions 匹配时仍视为 ready(UI 无 coverage 字段时按灰隙显示);新生成写 v2。
LEGACY_SCHEMAS = frozenset({"meeting-topic-map/v1"})
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
覆盖要求：一级论点必须覆盖全部窗口的候选论点材料，不得整窗丢弃；寒暄、过渡、等待、
纯展示等弱价值内容至多归入一个“过渡与杂项”类论点，并只为该论点携带 "low_value": true。

只输出 JSON：
{{"meeting_summary":"一句话说明整场推进", "topics":[
  {{"title":"一级论点", "summary":"该论点如何展开及当前结果",
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
    return "ready", value


def _default_llm(prompt: str, max_tokens: int) -> str:
    body = json.dumps({
        "model": MODEL,
        "temperature": 0.15,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": prompt}],
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        ROUTER, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=1800) as response:
        data = json.loads(response.read())
    return meeting_structure.clean_model_text(
        data["choices"][0]["message"].get("content", ""))


def _model_json(value) -> dict:
    if isinstance(value, dict):
        return value
    text = meeting_structure.clean_model_text(str(value or ""))
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
        target.extend(value for value in (values or []) if value not in target)

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
                    "children": [],
                }
                by_title[key] = group
                groups.append(group)
            summary = _plain(candidate.get("summary"), 360)
            if summary and summary not in group["summary_parts"]:
                group["summary_parts"].append(summary)
            for field in ("turn_ids", "claim_ids", "page_ids"):
                extend_unique(group[field], candidate.get(field))
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
            for field in ("turn_ids", "claim_ids", "page_ids", "children"):
                extend_unique(target[field], group[field])

    topics = []
    for group in groups:
        topics.append({
            "title": group["title"],
            "summary": " ".join(group["summary_parts"])[:500],
            "turn_ids": group["turn_ids"],
            "claim_ids": group["claim_ids"],
            "page_ids": group["page_ids"],
            "children": group["children"][:7],
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


def _sanitize_map(raw: dict, evidence: dict, revisions: dict, *, model: str,
                  window_count: int, chunk_seconds: float) -> dict:
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
        topic_turns, topic_claims, topic_pages = refs(raw_topic)
        children = []
        for raw_child in list(raw_topic.get("children") or [])[:8]:
            if not isinstance(raw_child, dict):
                continue
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
            "turn_ids": topic_turns, "claim_ids": topic_claims, "page_ids": topic_pages,
            "ranges": topic_ranges,
            "start": topic_ranges[0][0] if topic_ranges else None,
            "end": topic_ranges[-1][1] if topic_ranges else None,
            "children": children,
        })
    if not topics:
        raise ValueError("模型没有生成带有效证据的 Topic")

    # 确定性兜底:寒暄/过渡/纯展示等弱讨论时段常被模型丢弃,这里把未被任何 topic 挂接的
    # 连续 turn 段按时间邻接挂到最近的 topic。只扩展 turn_ids/ranges,不改写任何模型文本。
    covered_turns = {turn_id for topic in topics for turn_id in topic["turn_ids"]}
    gap_groups: list[list[dict]] = []
    previous_uncovered = False
    for turn in source_turns:
        if turn["id"] in covered_turns:
            previous_uncovered = False
            continue
        if not previous_uncovered:
            gap_groups.append([])
        gap_groups[-1].append(turn)
        previous_uncovered = True

    def gap_distance(topic: dict, start: float, end: float) -> float:
        distance = float("inf")
        for range_start, range_end in topic["ranges"]:
            if start <= range_end and range_start <= end:
                return 0.0
            distance = min(distance, abs(start - range_end), abs(range_start - end))
        return distance

    for group in gap_groups:
        group_start = float(group[0].get("start", 0))
        group_end = float(group[-1].get("end", 0))
        target = min(topics,
                     key=lambda topic: gap_distance(topic, group_start, group_end))
        target["turn_ids"] = list(dict.fromkeys(
            target["turn_ids"] + [turn["id"] for turn in group]))
        target["ranges"] = _merge_ranges(
            target["ranges"]
            + [[float(turn.get("start", 0)), float(turn.get("end", 0))] for turn in group])
        target["start"] = target["ranges"][0][0]
        target["end"] = target["ranges"][-1][1]

    # coverage = topic ranges 并集时长 ÷ 会议时长(由 turns 起止推算),供管线诊断。
    union_ranges = _merge_ranges(
        [bounds for topic in topics for bounds in topic["ranges"]], gap=0.0)
    covered_seconds = sum(end - start for start, end in union_ranges)
    meeting_start = min((float(turn.get("start", 0)) for turn in source_turns), default=0.0)
    meeting_end = max((float(turn.get("end", 0)) for turn in source_turns), default=0.0)
    duration = meeting_end - meeting_start
    coverage = round(min(1.0, covered_seconds / duration), 4) if duration > 0 else 0.0
    return {
        "schema": SCHEMA,
        "state": "ready",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "revisions": revisions,
        "generation": {"model": model,
                       "strategy": ("map-reduce/local-candidates-fallback-v1"
                                    if raw.get("_deterministic_fallback") else "map-reduce/v1"),
                       "chunk_seconds": chunk_seconds, "window_count": window_count},
        "meeting_summary": _plain(raw.get("meeting_summary"), 600),
        "topics": topics,
        "stats": {"topics": len(topics),
                  "children": sum(len(topic["children"]) for topic in topics),
                  "coverage": coverage},
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
        chunk_text = call(prompt, 2000)
        try:
            chunk_result = _model_json(chunk_text)
        except (json.JSONDecodeError, ValueError):
            print(f"[meta] Topic Map 局部归纳 {index}/{len(windows)} JSON 无效，正在修复格式",
                  flush=True)
            try:
                chunk_result = _repair_model_json(call, chunk_text, max_tokens=2600)
            except (json.JSONDecodeError, ValueError):
                # 单窗修复仍失败不再丢整场：空归纳交给 coverage 兜底做邻接分配。
                print(f"[warn] Topic Map 局部归纳 {index}/{len(windows)} 修复仍失败，"
                      "本窗按未覆盖处理", flush=True)
                chunk_result = {"summary": "", "candidate_topics": []}
        summaries.append(chunk_result)
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
            # 修复仍失败（多为输出截断）：完整重试一次归并；再失败时直接投影
            # 已有局部候选，避免整场脉络因为最终 JSON 包装失败而完全消失。
            print("[meta] Topic Map 全场归并修复仍失败，重试一次", flush=True)
            try:
                raw = _model_json(call(final_prompt, 8000))
            except (json.JSONDecodeError, ValueError):
                print("[warn] Topic Map 全场归并重试仍无合法 JSON，"
                      "改用局部候选确定性组装", flush=True)
                raw = _fallback_reduce(summaries)
    result = _sanitize_map(raw, evidence, revisions, model=model,
                           window_count=len(windows), chunk_seconds=chunk_seconds)
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
