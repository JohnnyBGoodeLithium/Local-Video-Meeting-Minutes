#!/usr/bin/env python3
"""Parse Microsoft Teams transcript exports without external dependencies.

Supported inputs:
- WebVTT exported by Teams
- DOCX exported by Teams (OOXML paragraphs with speaker, timestamp and text runs)

The parser returns the pipeline's canonical cue shape only. It never logs names or
transcript text, and it deliberately ignores avatars and other embedded media.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from meeting_core.live.vtt import WebVTTError, parse_webvtt


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"
MAX_DOCUMENT_XML_BYTES = 32 * 1024 * 1024
_DOCX_TIME = re.compile(r"(?<!\d)(?:(\d{1,3}):)?(\d{1,2}):(\d{2})(?![:\d])")
class TranscriptFormatError(ValueError):
    """The supplied file is readable but is not a supported Teams transcript."""


def to_sec(timestamp: str) -> float:
    parts = timestamp.replace(",", ".").split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    raise TranscriptFormatError("无法识别逐字稿时间码")


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_vtt(path: Path) -> list[dict]:
    """Parse Teams WebVTT into ``{name,start,end,text}`` cues."""
    try:
        cues = parse_webvtt(path)
    except WebVTTError as exc:
        raise TranscriptFormatError("VTT 中没有可用的 Teams 逐字稿段落") from exc
    return [{
        "name": cue.speaker or "未具名",
        "start": cue.start,
        "end": cue.end,
        "text": cue.text,
    } for cue in cues]


def _run_text(run: ET.Element) -> str:
    parts: list[str] = []
    for node in run.iter():
        if node.tag == W + "t":
            parts.append(node.text or "")
        elif node.tag in {W + "br", W + "cr", W + "tab"}:
            parts.append(" ")
    return "".join(parts)


def _is_bold(run: ET.Element) -> bool:
    prop = run.find(W + "rPr")
    if prop is None:
        return False
    bold = prop.find(W + "b")
    if bold is None:
        return False
    value = bold.get(W + "val")
    return value is None or value.lower() not in {"0", "false", "off"}


def _paragraph_cue(paragraph: ET.Element) -> dict | None:
    runs = list(paragraph.iter(W + "r"))
    if not runs:
        return None
    run_texts = [_run_text(run) for run in runs]
    time_index = -1
    time_match = None
    for index, text in enumerate(run_texts):
        match = _DOCX_TIME.search(text)
        if match:
            time_index, time_match = index, match
            break
    if time_match is None:
        return None

    # Current Teams DOCX exports place the display name in a bold run before
    # the timestamp. Requiring that relation avoids mistaking title/date headers
    # or timestamps quoted in the spoken body for transcript cues.
    speaker = _plain(" ".join(
        run_texts[index] for index in range(time_index)
        if _is_bold(runs[index]) and _plain(run_texts[index])
    ))
    if not speaker:
        return None

    after_time = run_texts[time_index][time_match.end():]
    text = _plain(" ".join([after_time, *run_texts[time_index + 1:]]))
    if not text:
        return None

    hours, minutes, seconds = time_match.groups()
    start = ((int(hours) * 3600 if hours is not None else 0)
             + int(minutes) * 60 + int(seconds))
    return {"name": speaker, "start": float(start), "text": text}


def _derive_docx_ends(cues: list[dict], duration: float | None) -> list[dict]:
    previous = -1.0
    for cue in cues:
        if cue["start"] < previous:
            raise TranscriptFormatError("DOCX 逐字稿时间码不是递增顺序")
        previous = cue["start"]

    for index, cue in enumerate(cues):
        next_start = next(
            (later["start"] for later in cues[index + 1:]
             if later["start"] > cue["start"]),
            None,
        )
        if next_start is not None:
            end = next_start
        elif duration is not None and duration > cue["start"]:
            end = duration
        else:
            end = cue["start"] + 5.0
        cue["end"] = max(cue["start"] + 0.25, float(end))
    return cues


def parse_docx(path: Path, duration: float | None = None) -> list[dict]:
    """Parse a Teams DOCX transcript using its OOXML run structure.

    DOCX exports contain cue start times but no explicit end times. Ends are
    derived from the next later cue; the last cue uses the media/diarization
    duration when supplied and otherwise receives a small safe tail.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_DOCUMENT_XML_BYTES:
                raise TranscriptFormatError("DOCX 逐字稿正文超过安全解析上限")
            document = archive.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise TranscriptFormatError("文件不是有效的 Teams DOCX 逐字稿") from exc
    try:
        root = ET.fromstring(document)
    except ET.ParseError as exc:
        raise TranscriptFormatError("DOCX 逐字稿 XML 已损坏") from exc

    cues = [cue for paragraph in root.iter(W + "p")
            if (cue := _paragraph_cue(paragraph)) is not None]
    if not cues:
        raise TranscriptFormatError("DOCX 中没有识别到 Teams 逐字稿段落")
    return _derive_docx_ends(cues, duration)


def parse_transcript(path: Path, duration: float | None = None) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".vtt":
        return parse_vtt(path)
    if suffix == ".docx":
        return parse_docx(path, duration=duration)
    raise TranscriptFormatError("Teams 逐字稿只支持 .vtt 或 .docx")
