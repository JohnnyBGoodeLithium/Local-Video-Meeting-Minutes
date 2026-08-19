#!/usr/bin/env python3
"""渐进式纪要状态回归：语音草稿先可读，多模态终稿后原位升级。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
import meeting_generation  # noqa: E402
from meeting_core.llm import (DEFAULT_DRAFT_MODEL, DEFAULT_MINUTES_MODEL,
                              minutes_model_for_stage)  # noqa: E402


assert minutes_model_for_stage("voice_draft") == DEFAULT_DRAFT_MODEL
assert minutes_model_for_stage("final") == DEFAULT_MINUTES_MODEL


def evidence(claims: list[dict]) -> dict:
    return {
        "schema": "meeting-minutes-evidence/v1",
        "claims": [{"id": f"C{index:05d}", **claim}
                   for index, claim in enumerate(claims, 1)],
    }


with tempfile.TemporaryDirectory(prefix="meeting-generation-test-") as temp:
    mdir = Path(temp)
    (mdir / "minutes.md").write_text("# 会议纪要\n\n- 语音草稿事实\n", encoding="utf-8")
    (mdir / "minutes.evidence.json").write_text(
        json.dumps(evidence([
            {"text": "语音草稿事实", "kind": "decision", "status": "confirmed",
             "turn_ids": ["T000001"]},
            {"text": "待屏幕核对", "kind": "action", "status": "open",
             "formal_action": True, "turn_ids": ["T000002"]},
        ]), ensure_ascii=False),
        encoding="utf-8")

    meeting_generation.update(mdir, "voice_draft_generating")
    draft = meeting_generation.publish_voice_draft(mdir)
    assert draft["phase"] == "voice_draft" and draft["voice_draft_claims"] == 2
    assert meeting_generation.document_state(mdir, True) == "draft"
    assert (mdir / "minutes.voice-draft.md").is_file()
    assert (mdir / "minutes.voice-draft.evidence.json").is_file()
    checklist = meeting_generation.voice_draft_checklist(mdir)
    assert checklist["schema"] == "meeting-voice-draft-checklist/v1"
    assert [item["kind"] for item in checklist["items"]] == ["action", "decision"]
    assert checklist["items"][0]["turn_ids"] == ["T000002"]

    meeting_generation.begin_visual_enrichment(mdir)
    assert meeting_generation.document_state(mdir, True) == "draft"
    (mdir / "minutes.md").write_text("# 会议纪要\n\n- 多模态终稿事实\n", encoding="utf-8")
    (mdir / "minutes.evidence.json").write_text(
        json.dumps(evidence([
            {"text": "语音草稿事实", "kind": "decision", "status": "confirmed",
             "turn_ids": ["T000001"]},
            {"text": "屏幕表格补充", "kind": "slide_fact", "status": "informational",
             "page_ids": ["P0001"]},
        ]), ensure_ascii=False),
        encoding="utf-8")
    final = meeting_generation.finalize(mdir, pages=12, vl_pages=10)
    assert final["phase"] == "ready"
    assert final["enrichment"] == {
        "pages": 12, "vl_pages": 10, "draft_claims": 2, "final_claims": 2,
        "added_claims": 1, "reframed_or_removed_claims": 1,
        "quality_state": "review_needed", "material_draft_claims": 2,
        "covered_material_claims": 1, "unresolved_material_claims": 1,
        "material_coverage": 0.5, "draft_actions": 1, "unresolved_actions": 1,
        "text_only_candidates": 0,
    }
    assert meeting_generation.document_state(mdir, True) == "ready"
    # 状态 sidecar 只存 revision/数量，不复制会议正文。
    state_text = (mdir / "meeting.generation.json").read_text(encoding="utf-8")
    assert "多模态终稿事实" not in state_text and "屏幕表格补充" not in state_text

    fully_covered = meeting_generation.coverage_audit(
        evidence([{"text": "落实合成方案", "kind": "action", "status": "open",
                   "formal_action": True, "turn_ids": ["T000009"]}]),
        evidence([{"text": "执行合成方案", "kind": "action", "status": "open",
                   "formal_action": True, "turn_ids": ["T000009", "T000010"]}]))
    assert fully_covered["quality_state"] == "pass"
    assert fully_covered["unresolved_actions"] == 0

    wrong_evidence = meeting_generation.coverage_audit(
        evidence([{"text": "同一句合成结论", "kind": "decision", "status": "confirmed",
                   "turn_ids": ["T000011"]}]),
        evidence([{"text": "同一句合成结论", "kind": "decision", "status": "confirmed",
                   "turn_ids": ["T000012"]}]))
    assert wrong_evidence["quality_state"] == "review_needed"
    assert wrong_evidence["text_only_candidates"] == 1

with tempfile.TemporaryDirectory(prefix="meeting-generation-legacy-") as temp:
    legacy = Path(temp)
    (legacy / "minutes.md").write_text("# 旧纪要\n", encoding="utf-8")
    assert meeting_generation.document_state(legacy, True) == "ready"

print("Meeting generation: voice draft -> visual enrichment -> ready")
