#!/usr/bin/env python3
"""Companion library/item projections contain only intentional fields."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "web"), str(ROOT / "bin")]
import companion_projection as projection  # noqa: E402


with tempfile.TemporaryDirectory(prefix="companion-library-") as tmp:
    root = Path(tmp)
    mdir = root / "synthetic-item"
    mdir.mkdir()
    (mdir / "meta.json").write_text(json.dumps({"title": "Synthetic Review",
                                                 "content_type": "meeting"}), encoding="utf-8")
    (mdir / "transcript.spk.json").write_text(json.dumps([
        {"speaker": "Speaker A", "voice": "v_1", "start": 1, "end": 4,
         "text": "Synthetic statement."}], ensure_ascii=False), encoding="utf-8")
    (mdir / "minutes.md").write_text("# Synthetic\n", encoding="utf-8")
    (mdir / "meeting.topic-map.json").write_text(json.dumps({
        "schema": "meeting-topic-map/v1", "state": "ready",
        "topics": [{"title": "Synthetic topic", "summary": "Safe summary"}],
    }), encoding="utf-8")
    (mdir / "minutes.evidence.json").write_text(json.dumps({"claims": [{
        "id": "C00001", "text": "Synthetic conclusion", "kind": "decision",
        "status": "confirmed", "confidence": "high", "turn_indexes": [0],
    }]}), encoding="utf-8")
    projection._meeting_identity = lambda _slug: {"title": "Synthetic Review",
                                                  "content_type": "meeting"}
    projection.meeting_topic_map.load_current_topic_map = lambda _mdir: ("ready", {
        "topics": [{"title": "Synthetic topic", "summary": "Safe summary"}]})
    projection._current_evidence = lambda _mdir: {"claims": [{
        "id": "C00001", "text": "Synthetic conclusion", "kind": "decision",
        "status": "confirmed", "confidence": "high", "turn_indexes": [0]}]}
    rows = projection.library(root)
    assert set(rows[0]) == {"id", "title", "content_type", "duration", "status",
                           "ready", "updated_at"}
    item = projection.item(mdir)
    encoded = json.dumps(item)
    assert "Synthetic topic" in encoded and "Synthetic conclusion" in encoded
    assert str(root) not in encoded and "voice_ids" not in encoded
    assert item["people"] == [{"name": "Speaker A", "moment_count": 1}]

print("companion library: safe recent/item projection passed")
