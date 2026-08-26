#!/usr/bin/env python3
"""知识库导出文档（kb document）：把单场内容收敛成一份自包含 Markdown。

面向本机 WeKnora 等"按文档分块"的知识库（KB 管理归知识库，本工具只做导出）：

- YAML front matter：title / date / content_type / duration / keywords（带 kind）/
  source_url（meta.json 里有才带）；
- 正文按分块友好顺序：总体摘要 → 关键结论 → 待办 → 议题脉络 → 屏幕内容 → 逐字稿；
- 所有时间码渲染成跳回本应用的深链 `[mm:ss](<base>/?meeting=<slug>&t=<秒>)`；
  头部放完整视频（无视频放音频）外链，屏幕图走
  `<base>/api/meetings/<slug>/file?path=` 外链，包体因此保持纯文本、体积极小；
- 依据标记保留纯文本 `#mm-C00001`，不转链接：锚是 viewer 内部机制，KB 里无意义，
  但文本要留着供检索；
- 生成语言跟随纪要主语言，不双语重复；只读会议目录，不调用模型；
- 缺失的板块（纪要 / 脉络 / 屏幕 / 关键字…）整节跳过。

base URL 取 env `MEETING_WEB_PUBLIC_BASE`，默认 `http://127.0.0.1:8899`。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import os
import re
import sys
import tempfile
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from markdown_it import MarkdownIt
from PIL import Image, ImageOps

from export_meeting import _document_language, _identity, _media_source, _read_json
from meeting_artifact import (FORMAL_ACTION_SECTIONS, WRAPPED_MARKER_RE,
                              _markdown_cell, action_items_from_claims,
                              build_evidence_document, load_speaker_profiles,
                              minutes_reading_markdown)
from meeting_structure import _visual_value, clean_model_text, visual_title
from meeting_core.source_info import load_source_info
import meeting_topic_map
from product_version import PRODUCT_VERSION, PRODUCT_VERSION_LABEL

KB_SCHEMA = "kb-pack/v1"
KB_HTML_SCHEMA = "meeting-kb-html/v1"
BASE_URL_ENV = "MEETING_WEB_PUBLIC_BASE"
DEFAULT_BASE_URL = "http://127.0.0.1:8899"
KEYWORD_KINDS = {"product", "project", "topic", "organization", "other"}
KB_HTML_IMAGE_EDGE = 1600
KB_HTML_IMAGE_QUALITY = 86
KB_MD = MarkdownIt("default", {"html": False, "linkify": True})

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
_SUMMARY_NAMES = ("总体摘要", "overallsummary", "summary")
_ACTION_NAMES = tuple(FORMAL_ACTION_SECTIONS) + (
    "actionitems", "actions", "todos", "todo", "nextsteps", "followups")
_CONCLUSION_RE = re.compile(
    r"^[-*]\s*\*\*\s*(关键结论|key\s+conclusions?|key\s+findings?|conclusions?)\s*\*\*",
    re.I)
_TOP_BULLET_RE = re.compile(r"^[-*]\s*\*\*")

_LABELS = {
    "zh-CN": {
        "summary": "总体摘要", "conclusions": "关键结论", "actions": "待办",
        "topics": "议题脉络", "screens": "屏幕内容", "transcript": "逐字稿",
        "full_video": "完整视频", "full_audio": "完整音频",
        "page": "第 {} 页", "tbd": "待确认", "speaker_colon": "：",
        "action_header": ("事项", "负责人", "期限", "状态"),
        "status": {"confirmed": "已确认", "working_alignment": "方向共识",
                   "proposal": "提议", "open": "待确认", "informational": "记录"},
    },
    "en": {
        "summary": "Overall Summary", "conclusions": "Key Conclusions",
        "actions": "Action Items", "topics": "Topic Outline",
        "screens": "Screen Content", "transcript": "Transcript",
        "full_video": "Full video", "full_audio": "Full audio",
        "page": "Page {}", "tbd": "TBD", "speaker_colon": ":",
        "action_header": ("Item", "Owner", "Deadline", "Status"),
        "status": {"confirmed": "confirmed", "working_alignment": "alignment",
                   "proposal": "proposal", "open": "open",
                   "informational": "informational"},
    },
}


def default_base_url() -> str:
    """知识库文档外链的 base：env 优先，默认 loopback；去掉尾部斜杠。"""
    return (os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL).strip().rstrip("/") \
        or DEFAULT_BASE_URL


def _norm_heading(title: str) -> str:
    value = unicodedata.normalize("NFKC", str(title or "")).strip()
    value = re.sub(r"^(?:\d+|[一二三四五六七八九十]+)\s*[.)、:：.．-]*\s*", "", value)
    return re.sub(r"[\s_\-:：/()（）.．]+", "", value).casefold()


def _find_section(markdown: str, names: tuple[str, ...]) -> str:
    """取第一个标题归一化后包含任一名字的章节正文（到同级或更高级标题为止）。"""
    matches = list(_HEADING_RE.finditer(markdown))
    for i, match in enumerate(matches):
        compact = _norm_heading(match.group(2))
        if not any(name in compact for name in names):
            continue
        level = len(match.group(1))
        end = len(markdown)
        for later in matches[i + 1:]:
            if len(later.group(1)) <= level:
                end = later.start()
                break
        return markdown[match.end():end].strip()
    return ""


def _drop_subsections(body: str, names: tuple[str, ...]) -> str:
    """从章节正文中删掉指定子节（如总体摘要内嵌的待办事项子节）。"""
    matches = list(_HEADING_RE.finditer(body))
    for i, match in enumerate(matches):
        compact = _norm_heading(match.group(2))
        if not any(name in compact for name in names):
            continue
        level = len(match.group(1))
        end = len(body)
        for later in matches[i + 1:]:
            if len(later.group(1)) <= level:
                end = later.start()
                break
        return (body[:match.start()].rstrip() + "\n\n" + body[end:].lstrip("\n")).strip()
    return body


def _split_key_conclusions(body: str) -> tuple[str, str]:
    """从总体摘要正文拆出 `- **关键结论**` 顶层列表块；返回 (剩余摘要, 结论块)。"""
    lines = body.splitlines()
    start = next((i for i, line in enumerate(lines) if _CONCLUSION_RE.match(line)), None)
    if start is None:
        return body, ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if _TOP_BULLET_RE.match(lines[j]) or _HEADING_RE.match(lines[j]):
            end = j
            break
    block = "\n".join(lines[start:end]).strip()
    rest = "\n".join(lines[:start] + lines[end:]).strip()
    return rest, block


def _markers_as_text(markdown: str, evidence: dict, *, base: str = "", slug: str = "",
                     label: str = "依据") -> str:
    """把 marker 转成可检索 C 编号；有时间时同时给出回看深链。"""
    by_marker: dict[str, list[dict]] = {}
    for claim in evidence.get("claims", []):
        by_marker.setdefault(str(claim.get("marker") or ""), []).append(claim)

    def replace(match: re.Match) -> str:
        queue = by_marker.get(match.group(1), [])
        claim = queue.pop(0) if queue else None
        if not claim:
            return ""
        marker = f"#mm-{claim['id']}"
        start = claim.get("start")
        if base and slug and start is not None:
            seconds = max(0.0, float(start))
            return f" {marker} [{label} · {_stamp(seconds)}]({_time_url(base, slug, seconds)})"
        return f" {marker}"

    return WRAPPED_MARKER_RE.sub(replace, markdown)


def _stamp(seconds: float) -> str:
    total = max(0, int(seconds or 0))
    if total >= 3600:
        return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"
    return f"{total // 60:02d}:{total % 60:02d}"


def _t_value(seconds: float) -> str:
    return f"{max(0.0, float(seconds)):.3f}".rstrip("0").rstrip(".") or "0"


def _time_url(base: str, slug: str, seconds: float) -> str:
    return f"{base}/?meeting={quote(str(slug))}&t={_t_value(seconds)}"


def _time_link(base: str, slug: str, seconds: float) -> str:
    return f"[{_stamp(seconds)}]({_time_url(base, slug, seconds)})"


def _file_url(base: str, slug: str, path: str) -> str:
    return f"{base}/api/meetings/{quote(str(slug))}/file?path={quote(str(path))}"


def _yaml_quote(value: str) -> str:
    """JSON 字符串转义是合法的 YAML 双引号标量。"""
    return json.dumps(str(value), ensure_ascii=False)


def _minutes_revision(minutes_path: Path | None) -> str | None:
    return (hashlib.sha256(minutes_path.read_bytes()).hexdigest()[:16]
            if minutes_path else None)


def _keyword_entries(mdir: Path, minutes_path: Path | None) -> list[dict]:
    """读取仍绑定当前纪要 revision 的关键字 sidecar；校验规则与 MeetingPack 导出一致。"""
    sidecar = _read_json(mdir / "meeting.keywords.json", {})
    entries = sidecar.get("keywords")
    if (sidecar.get("schema") != "meeting-keywords/v1"
            or sidecar.get("status") != "complete"
            or sidecar.get("source_revision") != _minutes_revision(minutes_path)
            or not isinstance(entries, list)):
        return []
    result = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        kind = str(item.get("kind") or "other").strip().lower()
        result.append({"text": text, "kind": kind if kind in KEYWORD_KINDS else "other"})
    return result


def _front_matter(title: str, date: str, content_type: str, duration: float,
                  keywords: list[dict], source_url: str) -> str:
    lines = ["---", f"title: {_yaml_quote(title)}"]
    if date:
        lines.append(f"date: {_yaml_quote(date)}")
    lines.append(f"content_type: {_yaml_quote(content_type)}")
    if duration > 0:
        lines.append(f"duration: {round(float(duration), 3)}")
    if keywords:
        lines.append("keywords:")
        for item in keywords:
            lines.append(f"  - {{text: {_yaml_quote(item['text'])}, "
                         f"kind: {_yaml_quote(item['kind'])}}}")
    if source_url:
        lines.append(f"source_url: {_yaml_quote(source_url)}")
    lines.append("---")
    return "\n".join(lines)


def _actions_table(actions: list[dict], labels: dict, *, base: str = "",
                   slug: str = "") -> str:
    """正式待办投影：与阅读纪要同一条 action_items_from_claims 链，依据编号保留纯文本。"""
    rows, seen = [], set()
    for action in actions:
        claim_id = str(action.get("claim_id") or "").strip()
        text = _markdown_cell(action.get("text"))
        if not (claim_id and text and action.get("turn_ids")):
            continue
        owner = _markdown_cell(action.get("owner")) or labels["tbd"]
        deadline = _markdown_cell(action.get("deadline")) or labels["tbd"]
        status = (_markdown_cell(action.get("status"))
                  or labels["status"].get(str(action.get("claim_status") or ""),
                                          labels["tbd"]))
        key = (text, owner, deadline, status)
        if key in seen:
            continue
        seen.add(key)
        start = action.get("start")
        evidence_link = ""
        if base and slug and start is not None:
            seconds = max(0.0, float(start))
            link_label = "Evidence" if labels["summary"] == "Overall Summary" else "依据"
            evidence_link = f" [{link_label} · {_stamp(seconds)}]({_time_url(base, slug, seconds)})"
        rows.append(f"| {text} #mm-{claim_id}{evidence_link} | {owner} | {deadline} | {status} |")
    if not rows:
        return ""
    header = labels["action_header"]
    return "\n".join([
        f"| {header[0]} | {header[1]} | {header[2]} | {header[3]} |",
        "| --- | --- | --- | --- |",
        *rows,
    ])


def _strip_headings(text: str) -> str:
    """VL 描述可能以 `# 标题` 开头；在文档正文里抹平标题层级，避免误拆知识库分块。"""
    return re.sub(r"^#{1,6}\s+", "", str(text or ""), flags=re.M).strip()


def kb_document(mdir: Path, *, base_url: str, bank_dir: Path | None = None,
                title: str | None = None, date: str | None = None,
                image_urls: dict[int, str] | None = None) -> str:
    """生成单场内容的自包含知识库 Markdown；只读会议目录，不调用模型。"""
    mdir = Path(mdir).resolve()
    base = str(base_url or "").strip().rstrip("/") or default_base_url()
    slug = mdir.name
    minutes_path = next((mdir / n for n in ("minutes.md", "minutes.spk.md")
                         if (mdir / n).is_file()), None)
    turns = _read_json(mdir / "transcript.spk.json", [])
    if minutes_path is None and not turns:
        raise ValueError("会议目录缺少 minutes.md 与 transcript.spk.json，无内容可导出")
    minutes = minutes_path.read_text(encoding="utf-8") if minutes_path else ""

    meta = _read_json(mdir / "meta.json", {})
    inferred_title, inferred_date = _identity(slug)
    title = title or str(meta.get("title") or "").strip() or inferred_title
    date = inferred_date if date is None else date
    content_type = (meta.get("content_type")
                    if meta.get("content_type") in ("meeting", "media") else "meeting")
    source_url = str(load_source_info(mdir).get("canonical_url") or "").strip()
    duration = max((float(t.get("end", 0)) for t in turns), default=0.0)
    keywords = _keyword_entries(mdir, minutes_path)

    language = _document_language(
        minutes or "\n".join(str(t.get("text") or "") for t in turns[:200]))
    labels = _LABELS["zh-CN" if language == "zh-CN" else "en"]

    # evidence 重建与 MeetingPack 导出同一条链：marker → claim 的映射只来自
    # canonical minutes + transcript，不写回会议目录。
    evidence = {"claims": []}
    reading = ""
    if minutes:
        if turns:
            timeline = _read_json(mdir / "slides.json", [])
            pages = [p for p in timeline
                     if p.get("kind", "slide") == "slide" and p.get("page") is not None]
            raw_desc = _read_json(mdir / "page_desc.json", {}).get("desc", {})
            descs = {int(k): clean_model_text(str(v)) for k, v in raw_desc.items()
                     if str(k).isdigit()}
            profiles = load_speaker_profiles(turns, bank_dir)
            evidence = build_evidence_document(
                mdir, minutes, turns, pages, descs, profiles,
                generation={"export_rebuilt": True})
        reading = minutes_reading_markdown(minutes, evidence, include_topic_section=False)

    parts = [_front_matter(title, date, content_type, duration, keywords, source_url),
             "", f"# {title}", ""]
    if _media_source(mdir, "video") is not None:
        parts += [f"[▶ {labels['full_video']}]({base}/api/meetings/{quote(slug)}/media/video)", ""]
    elif _media_source(mdir, "audio") is not None:
        parts += [f"[▶ {labels['full_audio']}]({base}/api/meetings/{quote(slug)}/media/audio)", ""]

    if reading:
        summary = _drop_subsections(_find_section(reading, _SUMMARY_NAMES), _ACTION_NAMES)
        summary, conclusions = _split_key_conclusions(summary)
        if summary:
            parts += [f"## {labels['summary']}", "",
                      _markers_as_text(summary, evidence, base=base, slug=slug,
                                       label="依据" if language == "zh-CN" else "Evidence"), ""]
        if conclusions:
            parts += [f"## {labels['conclusions']}", "",
                      _markers_as_text(conclusions, evidence, base=base, slug=slug,
                                       label="依据" if language == "zh-CN" else "Evidence"), ""]
        actions = _actions_table(action_items_from_claims(evidence.get("claims", [])),
                                 labels, base=base, slug=slug)
        if actions:
            parts += [f"## {labels['actions']}", "", actions, ""]

    turn_start = {f"T{index + 1:06d}": float(turn.get("start", 0))
                  for index, turn in enumerate(turns)}

    def node_time(node: dict) -> float | None:
        ranges = node.get("ranges") or []
        if ranges and ranges[0]:
            return float(ranges[0][0])
        starts = [turn_start[tid] for tid in node.get("turn_ids") or []
                  if tid in turn_start]
        return min(starts) if starts else None

    topic_state, topic_map = meeting_topic_map.load_current_topic_map(mdir)
    topics = topic_map.get("topics", []) if topic_state == "ready" else []
    if topics:
        parts += [f"## {labels['topics']}", ""]
        for topic in topics:
            heading = str(topic.get("title") or "").strip() or "—"
            start = node_time(topic)
            prefix = f"{_time_link(base, slug, start)} " if start is not None else ""
            parts += [f"### {prefix}{heading}", ""]
            topic_summary = str(topic.get("summary") or "").strip()
            if topic_summary:
                parts += [topic_summary, ""]
            for child in topic.get("children", []) or []:
                child_title = str(child.get("title") or "").strip()
                if not child_title:
                    continue
                child_start = node_time(child)
                child_prefix = (f"{_time_link(base, slug, child_start)} "
                                if child_start is not None else "")
                child_summary = str(child.get("summary") or "").strip()
                suffix = f"：{child_summary}" if child_summary else ""
                parts.append(f"- {child_prefix}{child_title}{suffix}")
            parts.append("")

    timeline = _read_json(mdir / "slides.json", [])
    pages = [p for p in timeline
             if p.get("kind", "slide") == "slide" and p.get("page") is not None]
    if pages:
        raw_desc = _read_json(mdir / "page_desc.json", {}).get("desc", {})
        descs = {int(k): clean_model_text(str(v)) for k, v in raw_desc.items()
                 if str(k).isdigit()}
        parts += [f"## {labels['screens']}", ""]
        for page in pages:
            number = int(page.get("page"))
            start = float(page.get("first", page.get("captured", 0)) or 0)
            page_label = labels["page"].format(number)
            parts += [f"### {page_label} {_time_link(base, slug, start)}", ""]
            image = str(page.get("image") or "")
            if (image and "/" not in image and not image.startswith(".")
                    and (mdir / "slides" / image).is_file()):
                image_url = (_file_url(base, slug, "slides/" + image)
                             if image_urls is None else image_urls.get(number))
                if image_url:
                    parts += [f"![{page_label}]({image_url})", ""]
            description = _strip_headings(descs.get(number, ""))
            if description:
                parts += [description, ""]

    if turns:
        parts += [f"## {labels['transcript']}", ""]
        colon = labels["speaker_colon"]
        for turn in turns:
            start = float(turn.get("start", 0))
            speaker = str(turn.get("speaker") or "").strip() or "?"
            text = " ".join(str(turn.get("text") or "").split())
            parts += [f"{_time_link(base, slug, start)} **{speaker}{colon}** {text}", ""]

    return "\n".join(parts).rstrip() + "\n"


def _kb_html_image(path: Path) -> tuple[str, int]:
    """把分析帧收敛成适合 KB 的 JPEG data URI；不写回会议目录。"""
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
            rgba = image.convert("RGBA")
            canvas = Image.new("RGB", rgba.size, "white")
            canvas.paste(rgba, mask=rgba.getchannel("A"))
            image = canvas
        else:
            image = image.convert("RGB")
        if max(image.size) > KB_HTML_IMAGE_EDGE:
            image.thumbnail((KB_HTML_IMAGE_EDGE, KB_HTML_IMAGE_EDGE), Image.Resampling.LANCZOS)
        stream = io.BytesIO()
        image.save(stream, format="JPEG", quality=KB_HTML_IMAGE_QUALITY,
                   optimize=True, progressive=True)
    data = stream.getvalue()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}", len(data)


def _embedded_page_images(mdir: Path) -> tuple[dict[int, str], dict]:
    """只内嵌有知识价值的屏幕帧；口播、空白、会议 UI 和低价值页不占包体。"""
    timeline = _read_json(mdir / "slides.json", [])
    raw_desc = _read_json(mdir / "page_desc.json", {}).get("desc", {})
    descriptions = {int(k): clean_model_text(str(v)) for k, v in raw_desc.items()
                    if str(k).isdigit()}
    images: dict[int, str] = {}
    source_bytes = embedded_bytes = skipped = 0
    for page in timeline:
        if page.get("kind", "slide") != "slide" or page.get("page") is None:
            continue
        number = int(page["page"])
        description = descriptions.get(number, "")
        value = _visual_value(description, visual_title(description, number),
                              "camera" if page.get("kind") == "camera" else "slide")
        role = str(page.get("content_role") or value.get("content_role") or "")
        information_value = str(page.get("information_value")
                                or value.get("information_value") or "unknown")
        if (page.get("talking_head") or role in {"blank", "camera", "meeting_ui", "transition"}
                or information_value == "low"):
            skipped += 1
            continue
        image_name = str(page.get("image") or "")
        slides_dir = (mdir / "slides").resolve()
        source = mdir / "slides" / f"full_{number:02d}.jpg"
        if not source.is_file():
            source = mdir / "slides" / image_name
        try:
            source = source.resolve()
            if (not image_name or not source.is_file()
                    or not source.is_relative_to(slides_dir)):
                skipped += 1
                continue
            source_bytes += source.stat().st_size
            uri, size = _kb_html_image(source)
        except (OSError, ValueError):
            skipped += 1
            continue
        images[number] = uri
        embedded_bytes += size
    return images, {
        "embedded_images": len(images),
        "skipped_images": skipped,
        "source_image_bytes": source_bytes,
        "embedded_image_bytes": embedded_bytes,
        "image_format": "image/jpeg",
        "image_edge": KB_HTML_IMAGE_EDGE,
        "image_quality": KB_HTML_IMAGE_QUALITY,
    }


def _strip_front_matter(markdown: str) -> str:
    if markdown.startswith("---\n"):
        end = markdown.find("\n---\n", 4)
        if end >= 0:
            return markdown[end + 5:].lstrip()
    return markdown


def kb_html_document(mdir: Path, *, base_url: str, bank_dir: Path | None = None,
                     title: str | None = None, date: str | None = None) -> tuple[str, dict]:
    """生成可直接上传 WeKnora 的单文件 HTML，图片使用 base64 data URI。"""
    mdir = Path(mdir).resolve()
    meta = _read_json(mdir / "meta.json", {})
    inferred_title, inferred_date = _identity(mdir.name)
    resolved_title = title or str(meta.get("title") or "").strip() or inferred_title
    resolved_date = inferred_date if date is None else date
    content_type = (meta.get("content_type")
                    if meta.get("content_type") in {"meeting", "media"} else "meeting")
    image_urls, image_stats = _embedded_page_images(mdir)
    markdown = kb_document(
        mdir, base_url=base_url, bank_dir=bank_dir, title=resolved_title,
        date=resolved_date, image_urls=image_urls)
    body = KB_MD.render(_strip_front_matter(markdown))
    language = _document_language(markdown)
    labels = ({"meta": "文档元数据", "type": "内容类型", "date": "日期",
               "images": "内嵌关键画面"} if language == "zh-CN" else
              {"meta": "Document metadata", "type": "Content type", "date": "Date",
               "images": "Embedded key frames"})
    metadata = (
        f'<section class="document-meta" aria-label="{html.escape(labels["meta"])}">'
        f'<p><strong>{html.escape(labels["type"])}：</strong>{html.escape(content_type)}'
        + (f' · <strong>{html.escape(labels["date"])}：</strong>{html.escape(resolved_date)}'
           if resolved_date else "")
        + f' · <strong>{html.escape(labels["images"])}：</strong>'
          f'{image_stats["embedded_images"]}</p></section>')
    document = f'''<!doctype html>
<html lang="{html.escape(language)}">
<head>
<meta charset="utf-8">
<meta name="generator" content="Meeting Minutes {html.escape(PRODUCT_VERSION_LABEL)}">
<meta name="meeting-kb-schema" content="{KB_HTML_SCHEMA}">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(resolved_title)}</title>
<style>
body{{font:16px/1.65 system-ui,sans-serif;max-width:1080px;margin:40px auto;padding:0 24px;color:#242424}}
h1,h2,h3{{line-height:1.3}} img{{display:block;max-width:100%;height:auto;margin:18px 0;border:1px solid #ddd}}
table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}}
.document-meta{{color:#616161;border-bottom:1px solid #ddd;margin-bottom:28px}}
</style>
</head>
<body data-schema="{KB_HTML_SCHEMA}">
{metadata}
{body}
</body>
</html>
'''
    return document, {**image_stats, "schema": KB_HTML_SCHEMA,
                      "document_bytes": len(document.encode("utf-8"))}


def kb_html_filename(name: str, first_date: str = "", now: datetime | None = None) -> str:
    stamp = (now or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")
    base = _safe_name(name) or "知识库图文版"
    date_part = f"_{first_date}" if first_date else ""
    return f"{base}{date_part}_{PRODUCT_VERSION_LABEL}_{stamp}.kb.html"


def write_kb_html(mdir: Path, out: Path, *, base_url: str | None = None,
                  bank_dir: Path | None = None, title: str | None = None,
                  date: str | None = None) -> dict:
    """原子写出单场 `.kb.html`，返回不含正文的体积/图片统计。"""
    document, stats = kb_html_document(
        mdir, base_url=(base_url or default_base_url()), bank_dir=bank_dir,
        title=title, date=date)
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".kb-html-", suffix=".html", dir=out.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        temp.write_text(document, encoding="utf-8")
        temp.replace(out)
    finally:
        temp.unlink(missing_ok=True)
    inferred_title, inferred_date = _identity(Path(mdir).name)
    resolved_title = title or str(_read_json(Path(mdir) / "meta.json", {}).get("title") or "").strip() or inferred_title
    resolved_date = inferred_date if date is None else date
    return {"path": str(out), "bytes": out.stat().st_size,
            "filename": kb_html_filename(resolved_title, resolved_date),
            "name": resolved_title, "product_version": PRODUCT_VERSION,
            "base_url": (base_url or default_base_url()).rstrip("/"), **stats}


def _normalize_keyword(text: str) -> str:
    """与 web/keyword_service.normalize_keyword 同一规则：NFKC + casefold + 去空白。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text)).casefold())


def _safe_name(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_()（）" else "_" for c in text).strip("_")


def kb_pack_filename(name: str, first_date: str = "", now: datetime | None = None) -> str:
    """命名沿用导出约定：名称 + 首个会议日期 + 产品版本 + 导出时间。"""
    stamp = (now or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")
    base = _safe_name(name) or "知识库包"
    date_part = f"_{first_date}" if first_date else ""
    return f"{base}{date_part}_{PRODUCT_VERSION_LABEL}_{stamp}.kbpack.zip"


def build_kb_pack(meetings: list[tuple[str, Path, str | None, str | None]], out: Path, *,
                  base_url: str | None = None, bank_dir: Path | None = None,
                  document_format: str = "markdown") -> dict:
    """构建多内容 KB 包；markdown 走外链，html 把关键画面嵌进每场文档。"""
    if not meetings:
        raise ValueError("知识库导出至少需要一场内容")
    if document_format not in {"markdown", "html"}:
        raise ValueError("document_format 必须是 markdown/html")
    base = (base_url or default_base_url()).rstrip("/")
    out = Path(out).resolve()
    files: dict[str, bytes] = {}
    documents = []
    tag_merged: dict[str, dict] = {}
    for slug, mdir, title, date in meetings:
        mdir = Path(mdir).resolve()
        image_stats = {}
        if document_format == "html":
            doc, image_stats = kb_html_document(
                mdir, base_url=base, bank_dir=bank_dir,
                title=title or None, date=date or None)
            arcname = f"{slug}.kb.html"
        else:
            doc = kb_document(mdir, base_url=base, bank_dir=bank_dir,
                              title=title or None, date=date or None)
            arcname = f"{slug}.kb.md"
        data = doc.encode("utf-8")
        files[arcname] = data
        minutes_path = next((mdir / n for n in ("minutes.md", "minutes.spk.md")
                             if (mdir / n).is_file()), None)
        entries = _keyword_entries(mdir, minutes_path)
        turns = _read_json(mdir / "transcript.spk.json", [])
        meta = _read_json(mdir / "meta.json", {})
        inferred_title, inferred_date = _identity(slug)
        documents.append({
            "slug": slug,
            "title": title or str(meta.get("title") or "").strip() or inferred_title,
            "date": date or inferred_date or "",
            "content_type": (meta.get("content_type")
                             if meta.get("content_type") in ("meeting", "media")
                             else "meeting"),
            "duration": round(max((float(t.get("end", 0)) for t in turns), default=0.0), 1),
            "file": arcname,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "keywords": [item["text"] for item in entries],
            "embedded_images": int(image_stats.get("embedded_images", 0)),
            "embedded_image_bytes": int(image_stats.get("embedded_image_bytes", 0)),
        })
        for item in entries:
            normalized = _normalize_keyword(item["text"])
            if not normalized:
                continue
            entry = tag_merged.setdefault(normalized, {"text_counts": {}, "kinds": [],
                                                       "slugs": []})
            entry["text_counts"][item["text"]] = entry["text_counts"].get(item["text"], 0) + 1
            if item["kind"] not in entry["kinds"]:
                entry["kinds"].append(item["kind"])
            if slug not in entry["slugs"]:
                entry["slugs"].append(slug)

    tags = []
    for normalized, entry in tag_merged.items():
        text = max(entry["text_counts"].items(), key=lambda kv: kv[1])[0]
        tags.append({"text": text, "normalized": normalized,
                     "kinds": entry["kinds"], "slugs": sorted(entry["slugs"])})
    tags.sort(key=lambda e: (-len(e["slugs"]), e["normalized"]))
    shared = [tag for tag in tags if len(tag["slugs"]) >= 2]

    if len(documents) > 1:
        name = shared[0]["text"] if shared else "知识库包"
        lines = [f"# {name}", "", "## 内容清单", ""]
        for index, item in enumerate(documents, 1):
            date_text = f"（{item['date']}）" if item["date"] else ""
            lines.append(f"{index}. {item['title']}{date_text} — {item['file']}")
        if shared:
            lines += ["", "## 贯穿关键字", ""]
            for tag in shared:
                lines.append(f"- {tag['text']}（{'、'.join(tag['kinds'])}）→ "
                             + "、".join(tag["slugs"]))
        files["index.md"] = ("\n".join(lines) + "\n").encode("utf-8")
    else:
        name = documents[0]["title"]

    manifest = {
        "schema": KB_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "generator": {"name": "Meeting Minutes", "version": PRODUCT_VERSION},
        "base_url": base,
        "document_format": document_format,
        "image_mode": "embedded_base64" if document_format == "html" else "external_url",
        "documents": documents,
        "tags": tags,
        "counts": {"documents": len(documents),
                   "keywords": sum(len(d["keywords"]) for d in documents),
                   "shared_keywords": len(shared),
                   "embedded_images": sum(d["embedded_images"] for d in documents)},
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False,
                                        indent=2).encode("utf-8")

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w") as archive:
        for arcname in sorted(files):
            archive.writestr(arcname, files[arcname],
                             compress_type=zipfile.ZIP_DEFLATED)
    first_date = next((item["date"] for item in documents if item["date"]), "")
    return {"path": str(out), "bytes": out.stat().st_size,
            "filename": kb_pack_filename(name, first_date),
            "name": name, "product_version": PRODUCT_VERSION,
            "base_url": base, **manifest["counts"]}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="生成知识库版导出（自包含 Markdown + 媒体/时间码外链）")
    parser.add_argument("meeting_dirs", type=Path, nargs="+", help="一个或多个会议目录")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--base-url", default=None,
                        help=f"深链/外链 base；默认取 env {BASE_URL_ENV}，"
                             f"缺省 {DEFAULT_BASE_URL}")
    parser.add_argument("--bank-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "speaker_bank")
    parser.add_argument("--format", choices=("markdown", "html"), default="markdown",
                        help="html：关键画面以内嵌 JPEG 写入每场 .kb.html")
    args = parser.parse_args()
    meetings = [(mdir.resolve().name, mdir.resolve(), None, None)
                for mdir in args.meeting_dirs]
    probe = Path(tempfile.gettempdir()) / f".kbpack-export-{os.getpid()}.zip"
    try:
        stats = build_kb_pack(meetings, args.out or probe,
                              base_url=args.base_url, bank_dir=args.bank_dir,
                              document_format=args.format)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        probe.unlink(missing_ok=True)
        print(f"导出失败: {exc}", file=sys.stderr)
        return 1
    final = Path(stats["path"])
    if args.out is None:
        target = Path.cwd() / stats["filename"]
        final.replace(target)
        final = target
    print(f"[meta] KB Pack: {final} | {stats['bytes']} bytes | "
          f"documents={stats['documents']} base={stats['base_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
