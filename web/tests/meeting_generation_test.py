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


def evidence(texts: list[str]) -> dict:
    return {
        "schema": "meeting-minutes-evidence/v1",
        "claims": [{"id": f"C{index:05d}", "text": text}
                   for index, text in enumerate(texts, 1)],
    }


with tempfile.TemporaryDirectory(prefix="meeting-generation-test-") as temp:
    mdir = Path(temp)
    (mdir / "minutes.md").write_text("# 会议纪要\n\n- 语音草稿事实\n", encoding="utf-8")
    (mdir / "minutes.evidence.json").write_text(
        json.dumps(evidence(["语音草稿事实", "待屏幕核对"]), ensure_ascii=False),
        encoding="utf-8")

    meeting_generation.update(mdir, "voice_draft_generating")
    draft = meeting_generation.publish_voice_draft(mdir)
    assert draft["phase"] == "voice_draft" and draft["voice_draft_claims"] == 2
    assert meeting_generation.document_state(mdir, True) == "draft"
    assert (mdir / "minutes.voice-draft.md").is_file()
    assert (mdir / "minutes.voice-draft.evidence.json").is_file()

    meeting_generation.begin_visual_enrichment(mdir)
    assert meeting_generation.document_state(mdir, True) == "draft"
    (mdir / "minutes.md").write_text("# 会议纪要\n\n- 多模态终稿事实\n", encoding="utf-8")
    (mdir / "minutes.evidence.json").write_text(
        json.dumps(evidence(["语音草稿事实", "屏幕表格补充"]), ensure_ascii=False),
        encoding="utf-8")
    final = meeting_generation.finalize(mdir, pages=12, vl_pages=10)
    assert final["phase"] == "ready"
    assert final["enrichment"] == {
        "pages": 12, "vl_pages": 10, "draft_claims": 2, "final_claims": 2,
        "added_claims": 1, "reframed_or_removed_claims": 1,
    }
    assert meeting_generation.document_state(mdir, True) == "ready"
    # 状态 sidecar 只存 revision/数量，不复制会议正文。
    state_text = (mdir / "meeting.generation.json").read_text(encoding="utf-8")
    assert "多模态终稿事实" not in state_text and "屏幕表格补充" not in state_text

with tempfile.TemporaryDirectory(prefix="meeting-generation-legacy-") as temp:
    legacy = Path(temp)
    (legacy / "minutes.md").write_text("# 旧纪要\n", encoding="utf-8")
    assert meeting_generation.document_state(legacy, True) == "ready"

print("Meeting generation: voice draft -> visual enrichment -> ready")
