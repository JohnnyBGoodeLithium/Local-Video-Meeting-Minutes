#!/usr/bin/env python3
"""会议关键字 sidecar：状态机、校验边界、dry-run 与自动触发（全虚构、无模型调用）。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
sys.path.insert(0, str(PROJECT / "web"))
import keyword_service as keywords  # noqa: E402
from routers import keywords as keyword_routes  # noqa: E402


EVIDENCE = {
    "schema": "meeting-minutes-evidence/v1",
    "claims": [
        {"id": "C00001", "kind": "decision", "status": "confirmed",
         "text": "虚构决定：暂停 Nova Lake 刷新计划。"},
        {"id": "C00002", "kind": "action", "status": "confirmed",
         "text": "虚构待办：评估 IC Mini 成本。", "formal_action": True},
        {"id": "C00003", "kind": "discussion", "status": "informational",
         "text": "虚构讨论：Longtail 口径对齐。"},
    ],
}

with tempfile.TemporaryDirectory(prefix="keyword-service-test-") as tmp:
    mdir = Path(tmp) / "meetings" / "synthetic"
    mdir.mkdir(parents=True)

    # 校验边界：kind 白名单、长度、大小写去重、上限、claim_ids 存在性。
    candidate = {"keywords": [
        {"text": "IC Mini", "kind": "product", "claim_ids": ["C00002", "C99999"]},
        {"text": "ic mini", "kind": "product"},
        {"text": "  Longtail  ", "kind": "unknown-kind", "claim_ids": ["C00003"]},
        {"text": "这是一个长度明显超过二十个字符上限的关键字词条", "kind": "topic"},
        {"text": "", "kind": "topic"},
        {"text": "Nova Lake", "kind": "project", "claim_ids": "not-a-list"},
        *[{"text": f"额外词{i}", "kind": "topic"} for i in range(12)],
    ]}
    cleaned = keywords._validate_keywords(candidate, {"C00001", "C00002", "C00003"})
    texts = [item["text"] for item in cleaned]
    assert texts[:3] == ["IC Mini", "Longtail", "Nova Lake"], texts
    assert cleaned[0]["claim_ids"] == ["C00002"]  # 不存在的引用被剔除
    assert cleaned[1]["kind"] == "other"          # 非白名单类别归 other
    assert "claim_ids" not in cleaned[2]          # 非法 claim_ids 整体丢弃
    assert len(cleaned) == keywords.MAX_KEYWORDS  # 上限截断

    # 无纪要：拒绝生成。
    try:
        keywords.generate_keywords(mdir, "Synthetic Meeting", EVIDENCE, dry_run=True)
        raise AssertionError("expected KeywordError without minutes")
    except keywords.KeywordError:
        pass
    assert keywords.keywords_payload(mdir)["state"] == "missing"

    (mdir / "minutes.md").write_text("# 会议纪要\n\n虚构正文。\n", encoding="utf-8")

    # 无材料：拒绝生成。
    try:
        keywords.generate_keywords(mdir, "Synthetic Meeting", {}, dry_run=True)
        raise AssertionError("expected KeywordError without claims")
    except keywords.KeywordError:
        pass

    # dry-run 生成与 revision 绑定。
    document = keywords.generate_keywords(mdir, "Synthetic Meeting", EVIDENCE, dry_run=True)
    assert document["status"] == "complete" and document["keywords"]
    assert document["model"] == "synthetic-dry-run"
    payload = keywords.keywords_payload(mdir)
    assert payload["state"] == "ready"
    assert keywords.keyword_texts(mdir) == [k["text"] for k in document["keywords"]]

    # facts revision 参与绑定：facts 出现/变化后旧关键字 stale。
    facts = {"schema": "meeting-facts/v1", "claims": [
        {"marker": "mm:C00009", "kind": "decision", "status": "confirmed",
         "text": "虚构事实：Neo 系列整合。"}]}
    (mdir / "meeting.facts.json").write_text(
        json.dumps(facts, ensure_ascii=False), encoding="utf-8")
    assert keywords.keywords_payload(mdir)["state"] == "stale"
    regenerated = keywords.generate_keywords(
        mdir, "Synthetic Meeting", EVIDENCE, dry_run=True)
    assert regenerated["facts_revision"] is not None
    assert keywords.keywords_payload(mdir)["state"] == "ready"

    # 纪要变化 → stale。
    (mdir / "minutes.md").write_text("# 会议纪要\n\n虚构正文（修订）。\n", encoding="utf-8")
    assert keywords.keywords_payload(mdir)["state"] == "stale"

    # 自动触发：ready 会议缺关键字时排一个低优先级作业，不重复排队。
    submitted = []
    created = []

    class CaptureExecutor:
        def submit(self, runner, job, *args):
            submitted.append(job["id"])

    def fake_job(kind, **fields):
        job = {"id": f"J{len(created) + 1}", "kind": kind, **fields}
        created.append(job)
        return job

    keyword_routes.EXEC = CaptureExecutor()
    keyword_routes._new_job = fake_job
    keyword_routes._minutes_file = lambda _mdir: _mdir / "minutes.md"
    keyword_routes._meeting_identity = lambda _slug: {"title": "Synthetic Meeting"}
    keyword_routes.meeting_generation.document_state = lambda *_args: "ready"
    keyword_routes.JOBS.clear()
    keyword_routes.JOBS.update({job["id"]: job for job in created})

    queued = keyword_routes.auto_keywords_after_ready("synthetic", mdir)
    assert len(queued) == 1 and submitted == queued
    assert created[0]["kind"] == "keywords" and created[0]["auto"] is True

    # 已 ready 时不排队；有活动作业时也不重复排队。
    keywords.generate_keywords(mdir, "Synthetic Meeting", EVIDENCE, dry_run=True)
    assert keyword_routes.auto_keywords_after_ready("synthetic", mdir) == []
    (mdir / "minutes.md").write_text("# 会议纪要\n\n再次修订。\n", encoding="utf-8")
    active = {"id": "JX", "kind": "keywords", "meeting": "synthetic", "status": "running"}
    keyword_routes.JOBS["JX"] = active
    assert keyword_routes.auto_keywords_after_ready("synthetic", mdir) == []

print("keyword service: payload/validation/dry-run/auto-trigger passed")
