#!/usr/bin/env python3
"""自然语言整篇重组：事实层独立、证据白名单与可逆写入。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
sys.path.insert(0, str(PROJECT / "web"))

import assistant_service as assistant  # noqa: E402
import meeting_artifact as artifact  # noqa: E402
import minutes_view_service  # noqa: E402
import rag_service  # noqa: E402


MARK_INFO = "<!-- mm:evidence kind=discussion status=informational confidence=high turns=T000001 -->"
MARK_ACTION = "<!-- mm:evidence kind=action status=open confidence=high turns=T000002 -->"


with tempfile.TemporaryDirectory(prefix="minutes-restructure-test-") as temp:
    mdir = Path(temp)
    turns = [
        {"speaker": "Alex Example", "start": 0.0, "end": 5.0, "text": "虚构背景信息。"},
        {"speaker": "Blair Example", "start": 5.0, "end": 9.0, "text": "虚构待办信息。"},
    ]
    transcript = mdir / "transcript.spk.json"
    transcript.write_text(json.dumps(turns, ensure_ascii=False), encoding="utf-8")
    minutes = mdir / "minutes.md"
    original = (
        "# 会议纪要\n\n## 总体摘要\n\n"
        f"- 虚构背景。 {MARK_INFO}\n\n"
        "## 待办事项\n\n"
        "| 事项 | 负责人 | 期限 | 状态 |\n| --- | --- | --- | --- |\n"
        f"| 完成虚构检查 {MARK_ACTION} | Blair Example | 周五 | 待确认 |\n"
    )
    minutes.write_text(original, encoding="utf-8")
    _path, evidence = artifact.write_evidence_document(
        mdir, original, turns, [], {}, [], generation={"synthetic": True})
    facts_path = mdir / "meeting.facts.json"
    facts_before = facts_path.read_bytes()
    facts = json.loads(facts_before)
    assert facts["schema"] == "meeting-facts/v1"
    assert facts["stats"]["claims"] == 2 and facts["stats"]["formal_actions"] == 1
    assert artifact.fact_document_state(mdir, facts) == "ready"
    repaired = assistant._attach_standalone_evidence_markers(
        f"# 会议纪要\n\n## 摘要\n\n- 虚构背景。\n\n{MARK_INFO}\n")
    assert f"- 虚构背景。 {MARK_INFO}" in repaired
    assistant._validate_restructured_minutes(repaired, facts)

    proposal = assistant.preview_minutes_restructure(
        minutes, transcript, mdir / "minutes.evidence.json",
        "先列背景，再列有依据的待办", assistant.revision(transcript),
        assistant.revision(minutes), True)
    assert proposal["scope"] == "document" and proposal["target_heading"] == "整篇纪要"
    assert proposal["proposal_id"] and proposal["sources"] and MARK_INFO in proposal["after"]
    try:
        assistant.apply_minutes_edit(minutes, proposal["proposal_id"])
        raise AssertionError("document proposal must not overwrite canonical minutes")
    except assistant.AssistantConflict:
        pass
    accepted = assistant.accept_minutes_view(minutes, proposal["proposal_id"])
    view = minutes_view_service.save_view(
        mdir, markdown=accepted["markdown"], summary=accepted["summary"],
        instruction="先列背景，再列有依据的待办",
        minutes_revision=accepted["minutes_revision"], sources=accepted["sources"])
    assert view["id"] and minutes.read_text(encoding="utf-8") == original
    assert minutes_view_service.list_views(mdir, assistant.revision(minutes))[0]["id"] == view["id"]
    assert facts_path.read_bytes() == facts_before
    rewritten = proposal["after"]
    _path, projected_evidence = artifact.write_evidence_document(
        mdir, rewritten, turns, [], {}, [], generation={"synthetic": True},
        update_facts=False)
    exported_records = artifact.rag_records(projected_evidence, rewritten, facts)
    assert any(row.get("record_type") == "fact" for row in exported_records), \
        "重组时省略的事实必须继续进入离线 RAG"
    online_records, online_meta = rag_service.meeting_records(mdir)
    assert online_meta["fact_state"] == "ready"
    assert online_meta["supplemental_fact_count"] >= 1
    assert any(row.get("type") == "fact" for row in online_records), \
        "重组时省略的事实必须继续进入在线 RAG"
    renamed_turns = [{**turn, "speaker": "Alex Renamed"} if index == 0 else turn
                     for index, turn in enumerate(turns)]
    transcript.write_text(json.dumps(renamed_turns, ensure_ascii=False), encoding="utf-8")
    _path, renamed_projection = artifact.write_evidence_document(
        mdir, rewritten, renamed_turns, [], {}, [], generation={"synthetic": True},
        update_facts=False)
    _path, refreshed_facts = artifact.refresh_fact_document_sources(
        mdir, renamed_projection)
    assert len(refreshed_facts["claims"]) == len(facts["claims"]) == 2
    assert len(renamed_projection["claims"]) == 1, \
        "测试必须证明窄阅读投影没有覆盖完整事实库存"
    assert refreshed_facts["claims"][0]["speakers"] == ["Alex Renamed"]
    assert artifact.fact_document_state(mdir, refreshed_facts) == "ready"
    assert minutes.read_text(encoding="utf-8") == original

    try:
        assistant._validate_restructured_minutes(
            "# 会议纪要\n\n## 摘要\n\n- 无依据事实。\n", facts)
        raise AssertionError("markerless fact must be rejected")
    except assistant.AssistantUnavailable:
        pass
    unknown = "<!-- mm:evidence kind=decision status=confirmed confidence=high turns=T999999 -->"
    try:
        assistant._validate_restructured_minutes(
            f"# 会议纪要\n\n## 摘要\n\n- 编造事实。 {unknown}\n", facts)
        raise AssertionError("unknown marker must be rejected")
    except assistant.AssistantUnavailable:
        pass
    repeated = (
        "# 会议纪要\n\n## 概览\n\n"
        f"- 虚构背景概览。 {MARK_INFO}\n\n"
        f"## 按人\n\n- Alex Example：虚构背景。 {MARK_INFO}\n")
    assistant._validate_restructured_minutes(repeated, facts)
    excessive = repeated + "".join(
        f"\n## 重复视角 {index}\n\n- 虚构重复背景。 {MARK_INFO}\n"
        for index in range(3, 10))
    try:
        assistant._validate_restructured_minutes(excessive, facts)
        raise AssertionError("more than eight uses of one fact must be rejected")
    except assistant.AssistantUnavailable:
        pass

    transcript.write_text(json.dumps([*renamed_turns, {
        "speaker": "Casey Example", "start": 9.0, "end": 10.0, "text": "来源改变。"
    }], ensure_ascii=False), encoding="utf-8")
    assert artifact.fact_document_state(mdir, facts) == "stale"

print("Minutes restructure/fact layer: synthetic fixture passed")
