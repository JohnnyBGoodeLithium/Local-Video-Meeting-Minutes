#!/usr/bin/env python3
"""ASR 术语 context 与屏幕候选的纯虚构回归。"""

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.terminology import (  # noqa: E402
    CANDIDATE_SCHEMA,
    build_context,
    harvest_screen_candidates,
    safe_harvest_screen_candidates,
    write_context_pack,
)


class FakeClient:
    def __init__(self, text=None, error=None):
        self.text = text
        self.error = error
        self.calls = 0

    def complete(self, *_args, **_kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.text)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    bank = base / "bank"
    meeting_a = base / "meetings" / "fictional-a"
    meeting_b = base / "meetings" / "fictional-b"
    bank.mkdir()
    meeting_a.mkdir(parents=True)
    meeting_b.mkdir(parents=True)

    store = {
        "schema": "meeting-terminology/v1",
        "terms": [{
            "id": "metric-example",
            "canonical": "Example Margin",
            "aliases": ["XM"],
            "meaning": "虚构财务指标",
            "status": "confirmed",
        }],
    }
    write_json(bank / "terminology.json", store)
    context, selected = build_context("Example planning", bank)
    assert "Example Margin" in context and len(selected) == 1

    transcript = meeting_a / "transcript.txt"
    transcript.write_text("unchanged fictional transcript", encoding="utf-8")
    context, meta = write_context_pack(meeting_a, "Example planning", bank)
    assert meta["schema"] == "meeting-asr-context/v1"
    assert meta["term_count"] == 1 and meta["policy"]["rewrites_transcript"] is False
    assert transcript.read_text(encoding="utf-8") == "unchanged fictional transcript"
    assert "context_sha256" in json.loads((meeting_a / "asr.context.json").read_text())

    response = json.dumps({"terms": [{
        "canonical": "ZXQ Platform",
        "meaning": "虚构产品平台",
        "category": "product",
        "confidence": "high",
    }]})
    write_json(meeting_a / "page_desc.json", {"desc": {"1": "ZXQ Platform roadmap"}})
    write_json(meeting_b / "page_desc.json", {"desc": {"1": "ZXQ Platform forecast"}})
    client = FakeClient(response)
    first = harvest_screen_candidates(meeting_a, "ZXQ review", bank, client=client)
    assert first["added"] == 1 and client.calls == 1
    context, _ = build_context("Another meeting", bank)
    assert "ZXQ Platform" not in context, "单场模型候选不得进入后续 ASR"

    second = harvest_screen_candidates(meeting_b, "ZXQ forecast", bank, client=client)
    assert second["updated"] == 1
    context, selected = build_context("Another meeting", bank)
    assert "ZXQ Platform" in context, "跨两场重复的高置信候选应可复用"
    candidates = json.loads((bank / "terminology.candidates.json").read_text())
    assert candidates["schema"] == CANDIDATE_SCHEMA
    assert len(candidates["terms"][0]["source_meetings"]) == 2

    empty = base / "empty"
    empty.mkdir()
    quiet_client = FakeClient(response)
    no_material = harvest_screen_candidates(empty, "No screens", bank, client=quiet_client)
    assert no_material["state"] == "no_screen_material" and quiet_client.calls == 0

    failed = safe_harvest_screen_candidates(
        meeting_a, "ZXQ review", bank, client=FakeClient(error=RuntimeError("private")))
    assert failed == {"added": 0, "updated": 0, "total": 0,
                      "state": "failed", "error_type": "RuntimeError"}

print("terminology tests: PASS")
