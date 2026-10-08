#!/usr/bin/env python3
"""Generic WebVTT parsing remains independent of Teams identity semantics."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.signals import generic_subtitle_signals
from meeting_core.live.vtt import WebVTTError, parse_webvtt_text


raw = """\ufeffWEBVTT

NOTE synthetic fixture
This is ignored.

cue-1
00:00:01.000 --> 00:00:03.500 position:10%
<c.caption>Hello &amp; welcome.</c>

00:01:04.250 --> 00:01:08.000
<v Avery Example>A named visual cue stays unconfirmed.</v>
"""
cues = parse_webvtt_text(raw)
assert [(cue.start, cue.end, cue.text) for cue in cues] == [
    (1.0, 3.5, "Hello & welcome."),
    (64.25, 68.0, "A named visual cue stays unconfirmed."),
]
assert cues[1].speaker == "Avery Example"
signals = generic_subtitle_signals(cues, language="en")
assert all(item.speaker is None and item.speaker_source == "unknown" for item in signals)
assert all(item.text_source == "native_subtitle" for item in signals)

# Legal cue identifiers beginning with reserved block words are not comments.
prefixed = "WEBVTT\n\n" + "\n\n".join(
    f"{identifier}\n00:00:0{index}.000 --> 00:00:0{index+1}.000\nSynthetic cue {index}."
    for index, identifier in enumerate(("NOTEworthy", "STYLE1", "REGIONfoo")))
assert [cue.text for cue in parse_webvtt_text(prefixed)] == [
    "Synthetic cue 0.", "Synthetic cue 1.", "Synthetic cue 2."]

try:
    parse_webvtt_text("WEBVTT\n\nno timing")
except WebVTTError:
    pass
else:
    raise AssertionError("empty WebVTT must be rejected")

print("generic VTT tests: OK")
