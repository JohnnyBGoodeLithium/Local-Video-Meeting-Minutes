#!/usr/bin/env python3
"""逐字稿翻译的优先批次、部分结果、取消与续跑（全虚构、无模型调用）。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
sys.path.insert(0, str(PROJECT / "web"))
import translation_service as translation  # noqa: E402
from routers import translations as translation_routes  # noqa: E402


with tempfile.TemporaryDirectory(prefix="translation-service-test-") as tmp:
    mdir = Path(tmp) / "meetings" / "synthetic"
    mdir.mkdir(parents=True)
    turns = [
        {
            "speaker": "Synthetic Speaker",
            "start": float(i),
            "end": float(i + 1),
            "text": (f"Synthetic English turn {i}." if i % 2
                     else f"虚构中文轮次{i}。"),
        }
        for i in range(25)
    ]
    source = json.dumps(turns, ensure_ascii=False, indent=1)
    (mdir / "transcript.spk.json").write_text(source, encoding="utf-8")
    progress_rows = []
    cancel = {"value": False}

    def on_progress(done: int, total: int) -> None:
        if done:
            document = json.loads(translation.sidecar_path(mdir).read_text(encoding="utf-8"))
            progress_rows.append([item["index"] for item in document.get("turns", [])])
            cancel["value"] = True

    try:
        translation.translate_transcript(
            mdir, "Synthetic Meeting", {}, dry_run=True,
            priority_indexes=lambda: [22], on_progress=on_progress,
            should_cancel=lambda: cancel["value"])
        raise AssertionError("expected cancellation")
    except translation.TranslationCancelled:
        pass

    partial = translation.translation_payload(mdir, "Synthetic Meeting", {})
    assert partial["state"] == "cancelled"
    assert partial["translated"] == 5
    assert progress_rows[0] == [20, 21, 22, 23, 24]
    assert (mdir / "transcript.spk.json").read_text(encoding="utf-8") == source

    resumed_progress = []
    completed = translation.translate_transcript(
        mdir, "Synthetic Meeting", {}, dry_run=True,
        on_progress=lambda done, total: resumed_progress.append((done, total)),
        should_cancel=lambda: False)
    assert resumed_progress[0] == (5, 25)
    assert completed["status"] == "complete"
    assert len(completed["turns"]) == 25
    assert translation.translation_payload(mdir, "Synthetic Meeting", {})["state"] == "ready"

    english = translation.translate_transcript(
        mdir, "Synthetic Meeting", {}, dry_run=True, target="en")
    assert english["target_language"] == "en"
    assert len(english["turns"]) == 25
    assert english["turns"][0]["source_language"] == "zh"
    assert "英语译文" in english["turns"][0]["translated_text"]
    assert english["turns"][1]["translated_text"] == turns[1]["text"]
    assert translation.sidecar_path(mdir, "en").name == "transcript.translation.en.json"
    assert translation.translation_payload(
        mdir, "Synthetic Meeting", {}, target="en")["state"] == "ready"

    minutes_source = """# 会议纪要

## 总体摘要

- 虚构结论。 <!-- mm:evidence kind=discussion status=informational confidence=high turns=T000001 -->
"""
    (mdir / "minutes.md").write_text(minutes_source, encoding="utf-8")
    before = translation.minutes_translation_payload(
        mdir, "Synthetic Meeting", minutes_source, {}, target="en")
    assert before["state"] == "missing" and before["source_language"] == "zh"
    minutes_document = translation.translate_minutes(
        mdir, "Synthetic Meeting", minutes_source, {}, dry_run=True, target="en")
    assert minutes_document["status"] == "complete"
    assert "# Meeting Minutes" in minutes_document["markdown"]
    assert "<!-- mm:evidence" in minutes_document["markdown"]
    ready = translation.minutes_translation_payload(
        mdir, "Synthetic Meeting", minutes_source, {}, target="en")
    assert ready["state"] == "ready" and not ready["is_source"]
    chinese = translation.minutes_translation_payload(
        mdir, "Synthetic Meeting", minutes_source, {}, target="zh-CN")
    assert chinese["state"] == "ready" and chinese["is_source"]

    topic_map = {
        "schema": "meeting-topic-map/v1", "state": "ready",
        "meeting_summary": "虚构的全场摘要。", "stats": {"topics": 1, "children": 1},
        "topics": [{
            "id": "M0001", "title": "虚构论点", "summary": "虚构论点摘要。",
            "ranges": [[12.0, 44.0]], "turn_ids": ["T000001"],
            "claim_ids": ["C0001"], "page_ids": ["P0001"],
            "children": [{"id": "M0001-N01", "type": "decision", "title": "虚构决定",
                          "summary": "虚构决定摘要。", "ranges": [[20.0, 30.0]],
                          "turn_ids": ["T000002"], "claim_ids": ["C0001"],
                          "page_ids": ["P0001"]}],
        }],
    }
    (mdir / "meeting.topic-map.json").write_text(
        json.dumps(topic_map, ensure_ascii=False, indent=2), encoding="utf-8")
    topic_before = translation.topic_map_translation_payload(mdir, topic_map, target="en")
    assert topic_before["state"] == "missing" and topic_before["source_language"] == "zh"
    translation.translate_topic_map(
        mdir, "Synthetic Meeting", topic_map, dry_run=True, target="en")
    topic_ready = translation.topic_map_translation_payload(mdir, topic_map, target="en")
    translated_map = topic_ready["topic_map"]
    assert topic_ready["state"] == "ready" and translated_map["topics"][0]["title"].startswith("English:")
    assert translated_map["topics"][0]["id"] == topic_map["topics"][0]["id"]
    assert translated_map["topics"][0]["ranges"] == topic_map["topics"][0]["ranges"]
    assert translated_map["topics"][0]["children"][0]["claim_ids"] == ["C0001"]
    topic_chinese = translation.topic_map_translation_payload(mdir, topic_map, target="zh-CN")
    assert topic_chinese["state"] == "ready" and topic_chinese["is_source"]

    page_desc = {"model": "synthetic-vl", "desc": {
        str(i): f"# 标题\n虚构屏幕页 {i}。展示合成数据，不代表会议决定。"
        for i in range(1, 14)
    }}
    (mdir / "page_desc.json").write_text(
        json.dumps(page_desc, ensure_ascii=False, indent=2), encoding="utf-8")
    visuals_before = translation.visuals_translation_payload(mdir, target="en")
    assert visuals_before["state"] == "missing" and visuals_before["total"] == 13
    visual_progress = []
    translation.translate_visuals(
        mdir, dry_run=True, target="en",
        on_progress=lambda done, total: visual_progress.append((done, total)))
    visuals_ready = translation.visuals_translation_payload(mdir, target="en")
    assert visuals_ready["state"] == "ready" and visuals_ready["translated"] == 13
    assert visuals_ready["pages"][0]["title"].startswith("English:")
    assert visual_progress == [(0, 13), (12, 13), (13, 13)]
    visuals_chinese = translation.visuals_translation_payload(mdir, target="zh-CN")
    assert visuals_chinese["state"] == "ready" and visuals_chinese["is_source"]
    page_desc["desc"]["1"] += " 修订。"
    (mdir / "page_desc.json").write_text(
        json.dumps(page_desc, ensure_ascii=False, indent=2), encoding="utf-8")
    assert translation.visuals_translation_payload(mdir, target="en")["state"] == "stale"

    # 自动补翻必须按资产自己的原文语言决定方向。例如纪要是
    # 中文，但 VL 模型可能输出英文；不能用纪要语言一刀切所有资产。
    submitted = []
    created = []

    class CaptureExecutor:
        def submit(self, runner, job, *args):
            submitted.append((job["translation_artifact"], job["target_language"]))

    def fake_job(kind, **fields):
        job = {"id": f"J{len(created) + 1}", "kind": kind, **fields}
        created.append(job)
        return job

    translation_routes.EXEC = CaptureExecutor()
    translation_routes._new_job = fake_job
    translation_routes._minutes_file = lambda _mdir: _mdir / "minutes.md"
    translation_routes._minutes_reading_source = lambda _mdir: ("synthetic", {})
    translation_routes._meeting_identity = lambda _slug: {"title": "Synthetic Meeting"}
    translation_routes._active_translation = lambda *_args: None
    translation_routes.meeting_generation.document_state = lambda *_args: "ready"
    translation_routes.meeting_topic_map.load_current_topic_map = lambda _mdir: (
        "ready", {"state": "ready", "topics": []})
    translation_routes.translation.minutes_translation_payload = (
        lambda *_args, target, **_kwargs: {"state": "ready" if target == "zh-CN" else "missing"})
    translation_routes.translation.topic_map_translation_payload = (
        lambda *_args, target, **_kwargs: {"state": "missing" if target == "zh-CN" else "ready"})
    translation_routes.translation.visuals_translation_payload = (
        lambda *_args, target, **_kwargs: {
            "state": "ready" if target == "zh-CN" else "missing", "total": 2,
            "translated": 0})
    queued = translation_routes.auto_translate_after_ready("synthetic", mdir)
    assert len(queued) == 3
    assert set(submitted) == {("minutes", "en"), ("topic_map", "zh-CN"), ("visuals", "en")}
    assert all(job.get("auto") is True for job in created)

print("Transcript, minutes, Topic Map, and visuals translation: structure and revisions passed")
