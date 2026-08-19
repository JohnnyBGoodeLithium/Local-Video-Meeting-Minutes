#!/usr/bin/env python3
"""ASR audio review and reversible transcript edits with fictional material."""

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "bin"), str(ROOT / "web")]

from meeting_core.transcript_review import (  # noqa: E402
    bind_review_to_transcript,
    find_candidates,
    review_term_confusions,
    write_review,
)
import transcript_service  # noqa: E402


class FakeProvider:
    name = "fictional-port"

    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []

    def transcribe(self, audio, *, context="", language=None, return_time_stamps=False):
        self.calls.append((len(audio), context, language, return_time_stamps))
        return [SimpleNamespace(text=text, language="Chinese", time_stamps=[],
                                context_applied=True) for text in self.outputs]


with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    bank = base / "bank"
    meeting = base / "meeting"
    bank.mkdir()
    meeting.mkdir()
    (bank / "terminology.json").write_text(json.dumps({
        "schema": "meeting-terminology/v1",
        "terms": [{"id": "metric-fictional", "canonical": "Example Margin",
                   "confusions": ["样例妈进"], "status": "confirmed"}],
    }, ensure_ascii=False), encoding="utf-8")
    sf.write(meeting / "audio.wav", np.zeros(8 * 16000, dtype=np.float32), 16000)
    text = "本轮讨论样例妈进和后续计划。"
    stamps = [
        {"text": value, "start_time": index * .35, "end_time": (index + 1) * .35}
        for index, value in enumerate(text)
    ]
    terms = [{"id": "metric-fictional", "canonical": "Example Margin",
              "confusions": ["样例妈进"]}]
    detected = find_candidates(text, stamps, terms)
    assert len(detected) == 1 and detected[0]["start"] < detected[0]["end"]

    provider = FakeProvider(["本轮讨论 Example Margin 和后续计划。"])
    corrected, corrected_stamps, review = review_term_confusions(
        provider, meeting / "audio.wav", text, stamps, "虚构会议上下文", bank,
        language="Chinese")
    assert corrected == "本轮讨论Example Margin和后续计划。"
    assert "Example Margin" in "".join(item["text"] for item in corrected_stamps)
    assert review["summary"] == {"checked": 1, "auto_corrected": 1, "pending": 0}
    assert provider.calls[0][0] == 1 and provider.calls[0][3] is False

    turns = [{"speaker": "Example Person", "voice": "v-example", "start": 0.0,
              "end": 8.0, "text": corrected}]
    (meeting / "transcript.spk.json").write_text(
        json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")
    (meeting / "transcript.spk.md").write_text(
        f"# Fictional transcript\n\n[00:00] **Example Person**: {corrected}\n",
        encoding="utf-8")
    write_review(meeting / "transcript.review.json", review)
    bound = bind_review_to_transcript(meeting)
    assert bound["items"][0]["turn_id"] == "T000001"

    before_revision = transcript_service.artifact.file_revision(meeting / "transcript.spk.json")
    edited = transcript_service.apply_text_edit(
        meeting, 0, "本轮讨论 Example Margin，并确认后续计划。", before_revision)
    assert edited["changed"] and edited["undo_available"]
    projected = transcript_service.project_review(meeting, evidence_current=False)
    assert projected["summary"]["human_corrected"] == 1
    assert projected["downstream_state"] == "sync_pending"
    assert list((meeting / ".versions").glob("before-transcript-edit-*"))

    undone = transcript_service.undo_latest(meeting)
    assert undone["ok"] and not undone["undo_available"]
    restored = json.loads((meeting / "transcript.spk.json").read_text(encoding="utf-8"))
    assert restored[0]["text"] == corrected
    assert transcript_service.artifact.file_revision(meeting / "transcript.spk.json") == before_revision

print("transcript review: ok")
