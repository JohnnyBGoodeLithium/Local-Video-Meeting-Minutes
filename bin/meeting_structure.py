#!/usr/bin/env python3
"""从既有纪要、视觉时间线和 evidence 确定性投影章节阅读结构。

不调用模型、不修改会议文件。逻辑页面负责复用 VL 解释；同一页面每次连续出现
都会展开为独立 Segment。Chapter 优先采用纪要中已有的“议题板块”，没有时
按连续视觉片段降级，保证旧会议也能浏览。
"""

from __future__ import annotations

import re
from collections import Counter

from meeting_artifact import MARKER_RE


SCHEMA = "meeting-structure/v1"
TOPIC_LINE_RE = re.compile(
    r"^\s*[-*+]\s*(?P<title>.+?)\s*[（(]\s*第\s*(?P<first>\d+)\s*"
    r"(?:[–—\-~至到]\s*(?P<last>\d+)\s*)?页\s*[，,]\s*"
    r"(?P<time>\d{1,3}:\d{2}(?::\d{2})?)\s*起?\s*[）)]\s*[：:]\s*(?P<summary>.+)$"
)


def _timestamp(value: str) -> float:
    parts = [int(part) for part in str(value).split(":")]
    if len(parts) == 3:
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    return float(parts[0] * 60 + parts[1])


def _plain(value: str) -> str:
    value = MARKER_RE.sub("", str(value or ""))
    value = value.replace("**", "").replace("__", "").replace("`", "")
    return " ".join(value.split()).strip()


def _visual_title(description: str, page: int) -> str:
    lines = [line.strip() for line in str(description or "").splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if re.match(r"^#{1,5}\s*标题\s*$", line):
            for following in lines[index + 1:]:
                if not following.startswith("#"):
                    return following.lstrip("-* ")[:100]
    for line in lines:
        cleaned = re.sub(r"^#{1,5}\s*", "", line).lstrip("-* ").strip()
        if cleaned and cleaned != "标题":
            return cleaned[:100]
    return f"第{page}页"


def _topic_rows(minutes: str) -> list[dict]:
    match = re.search(r"^##\s+议题板块\s*$", str(minutes or ""), re.M)
    if not match:
        return []
    following = str(minutes)[match.end():]
    end = re.search(r"^##\s+", following, re.M)
    section = following[:end.start()] if end else following
    rows = []
    for line in section.splitlines():
        parsed = TOPIC_LINE_RE.match(MARKER_RE.sub("", line))
        if not parsed:
            continue
        first = int(parsed.group("first"))
        last = int(parsed.group("last") or first)
        rows.append({
            "title": _plain(parsed.group("title")),
            "summary": _plain(parsed.group("summary")),
            "start": _timestamp(parsed.group("time")),
            "page_numbers": list(range(min(first, last), max(first, last) + 1)),
        })
    # 模型偶尔重复同一开始时间；保留第一条，后续再由时间范围确定结束点。
    unique = {}
    for row in sorted(rows, key=lambda item: item["start"]):
        unique.setdefault(row["start"], row)
    return list(unique.values())


def _turn_indexes(turns: list[dict], start: float, end: float) -> list[int]:
    result = []
    for index, turn in enumerate(turns):
        middle = (float(turn.get("start", 0)) + float(turn.get("end", 0))) / 2
        if start <= middle < end or (end <= start and middle == start):
            result.append(index)
    return result


def _claim_groups(claims: list[dict], turn_indexes: list[int], page_ids: list[str]) -> dict:
    turn_set, page_set = set(turn_indexes), set(page_ids)
    linked = []
    for claim in claims:
        claim_turns = set(claim.get("turn_indexes", []))
        claim_pages = set(claim.get("page_ids", []))
        if claim_turns.intersection(turn_set) or (not claim_turns and claim_pages.intersection(page_set)):
            linked.append(claim)
    actions = [claim["id"] for claim in linked if claim.get("kind") == "action"]
    open_items = [claim["id"] for claim in linked
                  if claim.get("status") in {"proposal", "open"}
                  or claim.get("kind") in {"risk", "open_question", "proposal"}]
    decisions = [claim["id"] for claim in linked
                 if claim["id"] not in set(actions + open_items)
                 and (claim.get("status") in {"confirmed", "working_alignment"}
                      or claim.get("kind") in {"decision", "alignment"})]
    reserved = set(decisions + actions + open_items)
    discussion = [claim["id"] for claim in linked if claim["id"] not in reserved]
    return {
        "claim_ids": [claim["id"] for claim in linked],
        "decision_claim_ids": list(dict.fromkeys(decisions)),
        "action_claim_ids": list(dict.fromkeys(actions)),
        "open_claim_ids": list(dict.fromkeys(open_items)),
        "discussion_claim_ids": discussion,
    }


def _segments(turns: list[dict], timeline: list[dict], descriptions: dict[int, str]) -> list[dict]:
    rows = []
    for item in timeline:
        kind = str(item.get("kind") or "slide")
        page = int(item["page"]) if kind == "slide" and item.get("page") is not None else None
        for range_index, bounds in enumerate(item.get("ranges", [])):
            if not isinstance(bounds, list) or len(bounds) != 2:
                continue
            start, end = float(bounds[0]), float(bounds[1])
            if end <= start:
                continue
            rows.append({
                "kind": kind,
                "page": page,
                "page_id": f"P{page:04d}" if page is not None else None,
                "start": start,
                "end": end,
                "image": item.get("image") if kind == "slide" else None,
                "range_index": range_index,
                "title": (_visual_title(descriptions.get(page, ""), page)
                          if page is not None else "摄像头画面"),
            })
    rows.sort(key=lambda item: (item["start"], item["end"]))
    camera_count = 0
    for index, row in enumerate(rows):
        row["id"] = f"S{index + 1:05d}"
        if row["page_id"]:
            row["visual_id"] = row["page_id"]
        else:
            camera_count += 1
            row["visual_id"] = f"V-CAMERA-{camera_count:03d}"
        row["turn_indexes"] = _turn_indexes(turns, row["start"], row["end"])
    return rows


def _fallback_chapters(segments: list[dict], duration: float) -> list[dict]:
    if not segments:
        return [{"title": "完整会议", "summary": "这场会议没有可用的共享画面分段。",
                 "start": 0.0, "end": duration, "page_numbers": [], "source": "meeting"}]
    rows = []
    if segments[0]["start"] > 1:
        rows.append({"title": "开场", "summary": "共享画面开始前的讨论。", "start": 0.0,
                     "end": segments[0]["start"], "page_numbers": [], "source": "visual"})
    for segment in segments:
        rows.append({"title": segment["title"],
                     "summary": ("这一时间段显示摄像头画面。" if segment["kind"] == "camera"
                                 else f"围绕第{segment['page']}页展开的讨论。"),
                     "start": segment["start"], "end": segment["end"],
                     "page_numbers": [segment["page"]] if segment["page"] else [],
                     "source": "visual"})
    if rows[-1]["end"] < duration:
        rows[-1]["end"] = duration
    return rows


def build_structure(minutes: str, turns: list[dict], timeline: list[dict],
                    descriptions: dict[int, str], evidence: dict,
                    duration: float | None = None) -> dict:
    duration = float(duration or max((turn.get("end", 0) for turn in turns), default=0))
    claims = list(evidence.get("claims", []))
    segments = _segments(turns, timeline, descriptions)
    topics = _topic_rows(minutes)
    if topics:
        chapters_raw = []
        if topics[0]["start"] > 1:
            chapters_raw.append({"title": "开场", "summary": "第一个议题开始前的讨论。",
                                 "start": 0.0, "page_numbers": [], "source": "minutes_topic"})
        chapters_raw.extend({**row, "source": "minutes_topic"} for row in topics)
        for index, row in enumerate(chapters_raw):
            row["end"] = (chapters_raw[index + 1]["start"]
                          if index + 1 < len(chapters_raw) else duration)
    else:
        chapters_raw = _fallback_chapters(segments, duration)

    chapters = []
    for raw in chapters_raw:
        start = max(0.0, min(duration, float(raw.get("start", 0))))
        end = max(start, min(duration, float(raw.get("end", duration))))
        indexes = _turn_indexes(turns, start, end)
        linked_segments = [segment for segment in segments
                           if segment["start"] < end and segment["end"] > start]
        page_ids = list(dict.fromkeys(
            [segment["page_id"] for segment in linked_segments if segment.get("page_id")]
            + [f"P{number:04d}" for number in raw.get("page_numbers", [])]
        ))
        speakers = Counter(str(turns[index].get("speaker") or "未知") for index in indexes)
        groups = _claim_groups(claims, indexes, page_ids)
        summary = raw.get("summary") or ""
        if not summary and groups["claim_ids"]:
            first_claim = next((claim for claim in claims
                                if claim["id"] == groups["claim_ids"][0]), None)
            summary = str((first_claim or {}).get("text") or "")
        chapters.append({
            "id": f"B{len(chapters) + 1:04d}",
            "title": raw.get("title") or f"章节 {len(chapters) + 1}",
            "summary": summary or "这一章节尚没有结构化摘要，可从逐字稿和画面继续核对。",
            "start": start,
            "end": end,
            "source": raw.get("source"),
            "segment_ids": [segment["id"] for segment in linked_segments],
            "page_ids": page_ids,
            "turn_indexes": indexes,
            "speakers": [name for name, _count in speakers.most_common(5)],
            **groups,
        })

    page_sources = {page.get("id"): page
                    for page in evidence.get("sources", {}).get("pages", [])}
    visuals = []
    slide_items = [item for item in timeline
                   if item.get("kind", "slide") == "slide" and item.get("page") is not None]
    for item in sorted(slide_items, key=lambda entry: int(entry["page"])):
        page = int(item["page"])
        pid = f"P{page:04d}"
        related_segments = [segment for segment in segments if segment.get("page_id") == pid]
        indexes = list(dict.fromkeys(index for segment in related_segments
                                     for index in segment["turn_indexes"]))
        source = page_sources.get(pid, {})
        groups = _claim_groups(claims, indexes, [pid])
        visuals.append({
            "id": pid, "kind": "slide", "page": page,
            "title": _visual_title(descriptions.get(page, ""), page),
            "description": descriptions.get(page, ""),
            "image": item.get("image"), "first": float(item.get("first", 0)),
            "ranges": item.get("ranges", []),
            "segment_ids": [segment["id"] for segment in related_segments],
            "turn_indexes": indexes,
            "display_status": source.get("display_status") or ("discussed" if indexes else "display_only"),
            **groups,
        })
    for segment in segments:
        if segment["kind"] != "camera":
            continue
        groups = _claim_groups(claims, segment["turn_indexes"], [])
        visuals.append({
            "id": segment["visual_id"], "kind": "camera", "page": None,
            "title": "摄像头画面", "description": "动态摄像头画面未进入静态页面 VL 解读。",
            "image": None, "first": segment["start"],
            "ranges": [[segment["start"], segment["end"]]],
            "segment_ids": [segment["id"]],
            "turn_indexes": segment["turn_indexes"], "display_status": "camera",
            **groups,
        })
    visuals.sort(key=lambda item: item["first"])
    return {
        "schema": SCHEMA,
        "chapter_source": "minutes_topic" if topics else "visual_segments",
        "segments": segments,
        "chapters": chapters,
        "visuals": visuals,
    }
