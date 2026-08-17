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


SCHEMA = "meeting-structure/v2"
TOPIC_LINE_RE = re.compile(
    r"^\s*[-*+]\s*(?P<title>.+?)\s*[（(]\s*第\s*(?P<first>\d+)\s*"
    r"(?:[–—\-~至到]\s*(?P<last>\d+)\s*)?页\s*[，,]\s*"
    r"(?P<time>\d{1,3}:\d{2}(?::\d{2})?)\s*起?\s*[）)]\s*[：:]\s*(?P<summary>.+)$"
)

REASONING_BLOCK_RE = re.compile(
    r"<(?:think|analysis)\b[^>]*>.*?</(?:think|analysis)\s*>", re.I | re.S)
REASONING_OPEN_RE = re.compile(r"<(?:think|analysis)\b[^>]*>", re.I)
REASONING_CLOSE_RE = re.compile(r"</(?:think|analysis)\s*>", re.I)
SPECIAL_TOKEN_RE = re.compile(r"<\|[^>]+\|>")
LOW_VALUE_RE = re.compile(
    r"(?:空白|黑屏|加载中|等待共享|无实质|没有实质|无有效|低信息|过渡页|章节页|分隔页|"
    r"纯装饰|会议界面|视频会议界面|摄像头画面|看不清|blank|loading|transition|divider)", re.I)
SUPPORTING_RE = re.compile(r"(?:封面|标题页|目录|议程|agenda|title slide|cover)", re.I)
HIGH_VALUE_RE = re.compile(
    r"(?:图表|表格|架构|流程|路线图|数据|指标|趋势|对比|方案|风险|结论|决策|"
    r"chart|table|architecture|workflow|roadmap|metric|trend)", re.I)


def clean_reasoning_text(value: str) -> str:
    """只清理 reasoning/特殊 token，保留 JSON、Markdown 等正文结构。"""
    text = str(value or "").replace("&lt;think&gt;", "<think>") \
        .replace("&lt;/think&gt;", "</think>") \
        .replace("&lt;analysis&gt;", "<analysis>") \
        .replace("&lt;/analysis&gt;", "</analysis>")
    text = REASONING_BLOCK_RE.sub("", text)
    # 只有 closing tag 时，前半通常是泄漏的 reasoning，答案在 tag 后。
    closers = list(REASONING_CLOSE_RE.finditer(text))
    if closers and not REASONING_OPEN_RE.search(text):
        text = text[closers[-1].end():]
    # 未闭合的 opening tag 没有可靠答案，宁可隐藏，也不把推理过程当标题。
    opener = REASONING_OPEN_RE.search(text)
    if opener:
        text = text[:opener.start()]
    text = REASONING_CLOSE_RE.sub("", text)
    text = SPECIAL_TOKEN_RE.sub("", text)
    text = re.sub(r"^\s*(?:assistant|final)\s*[:：]?\s*$", "", text,
                  flags=re.I | re.M)
    return text.strip()


def clean_model_text(value: str) -> str:
    """清理供人阅读的模型文案；会拆 VL 包装，不可用于 JSON 解析。"""
    text = clean_reasoning_text(value)
    # VL 偶发把答案包进 LaTeX \boxed{…} 并转义 Markdown（\## 标题）：先拆包装再还原转义，
    # 否则标题提取会把 \boxed{ 或 \## 标题 当成页面标题。
    text = re.sub(r"\\boxed\s*\{", "", text)
    text = re.sub(r"\\([#*_|~`>\[\](){}])", r"\1", text)
    text = re.sub(r"^[ \t]*[{}]+[ \t]*$", "", text, flags=re.M)
    return text.strip()


def _timestamp(value: str) -> float:
    parts = [int(part) for part in str(value).split(":")]
    if len(parts) == 3:
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    return float(parts[0] * 60 + parts[1])


def _plain(value: str) -> str:
    value = MARKER_RE.sub("", clean_model_text(value))
    value = value.replace("**", "").replace("__", "").replace("`", "")
    return " ".join(value.split()).strip()


def visual_title(description: str, page: int) -> str:
    lines = [line.strip() for line in clean_model_text(description).splitlines() if line.strip()]
    # VL 偶发把标题答成 JSON 片段："标题": "…",（boxed 包装被清洗后尤其常见）。
    for line in lines:
        json_title = re.match(
            r"^[\"{]*\s*[\"']?(?:标题|title)[\"']?\s*[:：]\s*[\"'](?P<v>.+?)[\"']\s*[,}]?\s*$",
            line, re.I)
        if json_title and json_title.group("v").strip():
            return json_title.group("v").strip()[:100]
    for index, line in enumerate(lines):
        if re.match(r"^#{1,5}\s*标题\s*$", line):
            for following in lines[index + 1:]:
                if not following.startswith("#"):
                    candidate = following.lstrip("-* ").strip("\"',")
                    if candidate:
                        return candidate[:100]
    for line in lines:
        cleaned = re.sub(r"^#{1,5}\s*", "", line).lstrip("-* ").strip().strip("\"',")
        if (cleaned and cleaned not in {"标题", "页面角色", "信息价值", "页面内容", "这页想说明什么"}
                and not re.match(r"^(?:content|agenda|cover|section|transition|blank|meeting_ui|demo)$",
                                 cleaned, re.I)
                and not re.match(r"^(?:high|medium|low|高|中|低)\s*[：:]", cleaned, re.I)):
            return cleaned[:100]
    return f"第{page}页屏幕内容"


# 保留内部别名，避免旧调用方一次性失效。导出器应使用公开的 visual_title。
_visual_title = visual_title


def _visual_role(description: str, title: str) -> str:
    text = f"{title}\n{description}"
    explicit = re.search(
        r"(?:页面角色|page role)[\"']?\s*[:：]?\s*[\"'`]?"
        r"(content|agenda|cover|section|transition|blank|meeting_ui|demo)",
        text, re.I | re.S)
    if explicit:
        return explicit.group(1).lower()
    if re.search(r"(?:空白|黑屏|blank)", text, re.I):
        return "blank"
    if re.search(r"(?:加载中|等待共享|会议界面|meeting[ _-]?ui)", text, re.I):
        return "meeting_ui"
    if re.search(r"(?:过渡页|章节页|分隔页|transition|divider|section)", text, re.I):
        return "transition"
    if re.search(r"(?:目录|议程|agenda)", text, re.I):
        return "agenda"
    if re.search(r"(?:封面|标题页|cover|title slide)", text, re.I):
        return "cover"
    return "content"


def _visual_value(description: str, title: str, kind: str = "slide") -> dict:
    """给屏幕内容打阅读价值标签；显式 VL 结论优先，旧缓存使用保守启发式。"""
    if kind == "camera":
        return {"content_role": "camera", "information_value": "low",
                "value_label": "低信息", "value_source": "deterministic",
                "value_reason": "摄像头动态画面不是静态页面资料。"}
    cleaned = clean_model_text(description)
    role = _visual_role(cleaned, title)
    if not cleaned:
        return {"content_role": role, "information_value": "unknown",
                "value_label": "待解析", "value_source": "unavailable",
                "value_reason": "页面说明尚未生成或没有可读正文，暂不评价内容价值。"}
    explicit = re.search(
        r"(?:信息价值|information value)[\"']?\s*[:：]?\s*[\"'`]?"
        r"(high|medium|low|高|中|低)", cleaned, re.I | re.S)
    normalized = {"高": "high", "中": "medium", "低": "low"}
    level = normalized.get(explicit.group(1), explicit.group(1).lower()) if explicit else None
    plain = _plain(cleaned)
    value_source = "vl" if level else "heuristic"
    if not level:
        if role in {"blank", "meeting_ui", "transition"} or LOW_VALUE_RE.search(plain):
            level = "low"
        elif role in {"agenda", "cover"} or SUPPORTING_RE.search(plain):
            level = "medium"
        elif HIGH_VALUE_RE.search(plain) or len(plain) >= 260:
            level = "high"
        elif len(plain) < 70:
            # 简短说明不等于页面没有价值。只有明确的空白/过渡/会议 UI 信号
            # 才能降为 low；旧缓存信息不足时保守保留为参考。
            level = "medium"
        else:
            level = "medium"
    reason_match = re.search(
        r"(?:信息价值|information value)\s*[:：]?\s*(?:`)?"
        r"(?:high|medium|low|高|中|低)(?:`)?\s*[：:—-]?\s*([^\n#]+)", cleaned, re.I)
    if reason_match:
        reason = _plain(reason_match.group(1))
    elif level == "low":
        reason = "封面、过渡、空白或会议界面，缺少可复用的业务信息。"
    elif level == "high":
        reason = "包含数据、结构、方案或其他可复用的核心信息。"
    else:
        reason = "提供议程、标题或辅助背景，可作为讨论定位参考。"
    return {"content_role": role, "information_value": level,
            "value_label": {"high": "核心", "medium": "参考", "low": "低信息"}[level],
            "value_source": value_source,
            "value_reason": (("根据旧页面说明推测：" + reason)
                             if value_source == "heuristic" else reason)}


def _display_description(description: str) -> str:
    """页面角色/信息价值已单独显示为 badge，正文里不再重复这两个元数据节。"""
    text = clean_model_text(description)
    for heading in ("页面角色", "信息价值"):
        text = re.sub(
            rf"^#{{1,5}}\s*{heading}\s*$.*?(?=^#{{1,5}}\s|\Z)", "", text,
            flags=re.M | re.S)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _short_chapter_title(raw_title: str, claims: list[dict], claim_ids: list[str],
                         page_ids: list[str], descriptions: dict[int, str], index: int) -> str:
    title = _plain(raw_title)
    invalid = (not title or len(title) > 72 or "<think" in title.lower()
               or title.lower() in {"analysis", "assistant", "标题", "页面内容"})
    if not invalid:
        return title
    claim_map = {claim.get("id"): claim for claim in claims}
    for claim_id in claim_ids:
        text = _plain((claim_map.get(claim_id) or {}).get("text"))
        if text:
            return text[:42] + ("…" if len(text) > 42 else "")
    for page_id in page_ids:
        try:
            page = int(str(page_id).lstrip("P"))
        except ValueError:
            continue
        title = _visual_title(descriptions.get(page, ""), page)
        if title:
            return title
    return f"章节 {index}"


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
    actions = [claim["id"] for claim in linked
               if claim.get("formal_action", claim.get("kind") == "action")]
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
            title = (_visual_title(descriptions.get(page, ""), page)
                     if page is not None else "摄像头画面")
            rows.append({
                "kind": kind,
                "page": page,
                "page_id": f"P{page:04d}" if page is not None else None,
                "start": start,
                "end": end,
                "image": item.get("image") if kind == "slide" else None,
                "range_index": range_index,
                "title": title,
                **_visual_value(descriptions.get(page, ""), title, kind),
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
        return [{"title": "会议讨论", "summary": "这场会议没有可用的共享画面分段。",
                 "start": 0.0, "end": duration, "page_numbers": [], "source": "meeting"}]
    # 页面变化不等于主题变化。空白、过渡、会议 UI 等低信息片段只归入相邻章节，
    # 不再各自生成一个没有业务意义的章节标题。
    anchors = [segment for segment in segments
               if segment.get("information_value") in {"high", "medium"}]
    if not anchors:
        return [{"title": "会议讨论", "summary": "共享画面以低信息或过渡内容为主。",
                 "start": 0.0, "end": duration, "page_numbers": [], "source": "visual"}]
    rows = []
    if anchors[0]["start"] > 60:
        rows.append({"title": "开场", "summary": "共享画面开始前的讨论。", "start": 0.0,
                     "end": anchors[0]["start"], "page_numbers": [], "source": "visual"})
    for index, segment in enumerate(anchors):
        start = segment["start"] if rows else 0.0
        end = anchors[index + 1]["start"] if index + 1 < len(anchors) else duration
        rows.append({"title": segment["title"],
                     "summary": ("这一时间段显示摄像头画面。" if segment["kind"] == "camera"
                                 else f"围绕第{segment['page']}页展开的讨论。"),
                     "start": start, "end": end,
                     "page_numbers": [segment["page"]] if segment["page"] else [],
                     "source": "visual"})
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
        summary = _plain(raw.get("summary") or "")
        if not summary and groups["claim_ids"]:
            first_claim = next((claim for claim in claims
                                if claim["id"] == groups["claim_ids"][0]), None)
            summary = _plain((first_claim or {}).get("text") or "")
        chapter_number = len(chapters) + 1
        chapters.append({
            "id": f"B{chapter_number:04d}",
            "title": _short_chapter_title(
                raw.get("title") or "", claims, groups["claim_ids"], page_ids,
                descriptions, chapter_number),
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
        title = _visual_title(descriptions.get(page, ""), page)
        description = clean_model_text(descriptions.get(page, ""))
        has_cached_description = page in descriptions
        visuals.append({
            "id": pid, "kind": "slide", "page": page,
            "title": title,
            "description": description,
            "display_description": _display_description(description),
            "image": item.get("image"), "first": float(item.get("first", 0)),
            "ranges": item.get("ranges", []),
            "segment_ids": [segment["id"] for segment in related_segments],
            "turn_indexes": indexes,
            "display_status": source.get("display_status") or ("discussed" if indexes else "display_only"),
            "analysis_state": ("ready" if description else
                               "failed" if has_cached_description else "pending"),
            "needs_reprocess": bool(has_cached_description and not description),
            **_visual_value(description, title),
            **groups,
        })
    for segment in segments:
        if segment["kind"] != "camera":
            continue
        groups = _claim_groups(claims, segment["turn_indexes"], [])
        visuals.append({
            "id": segment["visual_id"], "kind": "camera", "page": None,
            "title": "摄像头画面", "description": "动态摄像头画面未进入静态页面 VL 解读。",
            "display_description": "动态摄像头画面未进入静态页面 VL 解读。",
            "image": None, "first": segment["start"],
            "ranges": [[segment["start"], segment["end"]]],
            "segment_ids": [segment["id"]],
            "turn_indexes": segment["turn_indexes"], "display_status": "camera",
            **_visual_value("", "摄像头画面", "camera"),
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
