#!/usr/bin/env python3
"""Deterministic Chinese, English, mixed, long-turn and speaker caption contracts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))
import caption_projection as captions  # noqa: E402


turns = [
    {"id": "T000001", "speaker": "Speaker A", "voice": "v_1", "start": 0,
     "end": 18, "text": "这是一个很长的虚构中文句子，用来验证字幕会按照标点和时间稳定切分，而且不会跨越说话人边界。"},
    {"id": "T000002", "speaker": "Speaker A", "voice": "v_1", "start": 18,
     "end": 22, "text": "A deterministic English caption follows."},
    {"id": "T000003", "speaker": "Speaker B", "voice": "v_2", "start": 35,
     "end": 39, "text": "混合 caption 只使用已有文本。"},
]
profiles = [
    {"speaker": "Speaker A", "voice_ids": ["v_1"], "person_id": "P001", "display_name": "Luca"},
    {"speaker": "Speaker B", "voice_ids": ["v_2"], "person_id": None, "display_name": "Speaker B"},
]
translation = {"state": "ready", "source_revision": "rev-1", "turns": [
    {"index": 0, "translated_text": "A long synthetic Chinese turn translated for testing."},
    {"index": 1, "translated_text": "确定性的英文字幕。"},
    {"index": 2, "translated_text": "A mixed caption uses existing text only."},
]}
cues = captions.build_cues(turns, profiles=profiles, translation=translation)
assert len(cues) >= 5
assert all(cue["end"] > cue["start"] and cue["end"] - cue["start"] <= 6.01 for cue in cues)
assert all(cue["turn_id"] in {"T000001", "T000002", "T000003"} for cue in cues)
assert {cue["language"] for cue in cues} >= {"zh", "en", "mixed"}
assert cues[0]["person_id"] == "P001" and cues[0]["display_speaker"] == "Luca"

source = captions.render_vtt(cues, mode="source", content_type="meeting")
assert source.startswith("WEBVTT\n") and source.count("Luca:") == 1
assert "Speaker B:" in source
translated = captions.render_vtt(cues, mode="translation", speaker="hide")
assert "A long synthetic" in translated and "Luca:" not in translated
bilingual = captions.render_vtt(cues, mode="bilingual")
assert "确定性的英文字幕" in bilingual
escaped = captions.render_vtt([{**cues[0], "original_text": "bad --> cue"}])
assert "bad --> cue" not in escaped

stale = captions.build_cues(turns, profiles=profiles,
                            translation={"state": "stale", "turns": translation["turns"]})
assert all(cue["translated_text"] is None for cue in stale)
print("caption projection: Chinese/English/mixed segmentation, speaker and stale translation passed")
