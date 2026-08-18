#!/usr/bin/env python3
"""Teams VTT/DOCX transcript parser regression tests (fictional data only)."""

import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

import teams_transcript
from teams_transcript import TranscriptFormatError, parse_docx, parse_transcript, parse_vtt


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"


def run(parent, text, bold=False, line_break=False):
    item = ET.SubElement(parent, W + "r")
    if bold:
        props = ET.SubElement(item, W + "rPr")
        ET.SubElement(props, W + "b")
    if line_break:
        ET.SubElement(item, W + "br")
    node = ET.SubElement(item, W + "t")
    node.text = text


def make_docx(path: Path, cues: list[tuple[str, str, str]]):
    document = ET.Element(W + "document")
    body = ET.SubElement(document, W + "body")
    header = ET.SubElement(body, W + "p")
    run(header, "Fictional project sync", bold=True)
    date = ET.SubElement(body, W + "p")
    run(date, "January 1, 2030 09:00")
    for speaker, timestamp, text in cues:
        paragraph = ET.SubElement(body, W + "p")
        run(paragraph, speaker, bold=True, line_break=True)
        run(paragraph, timestamp)
        run(paragraph, text, line_break=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", ET.tostring(
            document, encoding="utf-8", xml_declaration=True))


with tempfile.TemporaryDirectory(prefix="mm_teams_transcript_") as tmp:
    tmpdir = Path(tmp)
    docx = tmpdir / "fictional.docx"
    make_docx(docx, [
        ("Alice Example", "0:03", "Opened the review."),
        ("王示例", "0:07", "确认 roadmap 范围。"),
        ("Bob Example", "1:02:03", "Closed the fictional session."),
    ])
    cues = parse_docx(docx, duration=3730.0)
    assert len(cues) == 3
    assert cues[0] == {
        "name": "Alice Example", "start": 3.0, "end": 7.0,
        "text": "Opened the review.",
    }
    assert cues[1]["name"] == "王示例" and cues[1]["end"] == 3723.0
    assert cues[2]["start"] == 3723.0 and cues[2]["end"] == 3730.0
    assert parse_transcript(docx, duration=3730.0) == cues

    duplicate = tmpdir / "duplicate.docx"
    make_docx(duplicate, [
        ("Alice Example", "0:03", "First cue."),
        ("Bob Example", "0:03", "Second cue."),
        ("Alice Example", "0:06", "Third cue."),
    ])
    duplicate_cues = parse_docx(duplicate, duration=9.0)
    assert [cue["end"] for cue in duplicate_cues] == [6.0, 6.0, 9.0]

    invalid = tmpdir / "headers-only.docx"
    make_docx(invalid, [])
    try:
        parse_docx(invalid)
    except TranscriptFormatError:
        pass
    else:
        raise AssertionError("headers-only DOCX must be rejected")

    oversized = tmpdir / "oversized.docx"
    old_limit = teams_transcript.MAX_DOCUMENT_XML_BYTES
    teams_transcript.MAX_DOCUMENT_XML_BYTES = 8
    try:
        make_docx(oversized, [("Alice Example", "0:01", "Fictional cue.")])
        try:
            parse_docx(oversized)
        except TranscriptFormatError:
            pass
        else:
            raise AssertionError("oversized document.xml must be rejected")
    finally:
        teams_transcript.MAX_DOCUMENT_XML_BYTES = old_limit

    vtt = tmpdir / "fictional.vtt"
    vtt.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n"
        "<v Alice Example>Hello from a fictional meeting.</v>\n",
        encoding="utf-8",
    )
    assert parse_vtt(vtt)[0]["name"] == "Alice Example"
    assert parse_transcript(vtt)[0]["end"] == 4.0

print("teams transcript tests: OK")
