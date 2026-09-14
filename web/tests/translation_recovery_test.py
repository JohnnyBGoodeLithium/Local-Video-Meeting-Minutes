#!/usr/bin/env python3
"""合成脉络翻译：固定节点、有限重试、取消、诊断和队列快照。"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "web"), str(ROOT / "bin")]

with tempfile.TemporaryDirectory(prefix="translation-recovery-test-") as tmp:
    os.environ["MEETING_DATA_ROOT"] = tmp
    os.environ["MEETING_WEB_JOBS"] = str(Path(tmp) / "jobs")
    (Path(tmp) / "jobs").mkdir()
    import translation_service as translation
    import job_store
    from job_progress import normalize_job_progress
    from routers import jobs, translations

    mdir = Path(tmp) / "meetings" / "synthetic"
    mdir.mkdir(parents=True)
    source = {"meeting_summary": "虚构的会议摘要。", "topics": [{
        "id": f"M{i:02}", "title": f"虚构主题{i}", "summary": "虚构讨论摘要。",
        "ranges": [[i * 10, i * 10 + 8]], "turn_ids": [f"T{i:03}"],
        "children": [{"id": f"M{i:02}-01", "title": "虚构子项", "summary": "虚构子项摘要。",
                      "claim_ids": [f"C{i:03}"], "ranges": [[i * 10, i * 10 + 3]]}],
    } for i in range(5)]}
    for name, text in (("meeting.topic-map.json", json.dumps(source, ensure_ascii=False)),
                       ("minutes.md", "# 虚构纪要"), ("transcript.spk.json", "[]")):
        (mdir / name).write_text(text)
    original = {p.name: p.read_bytes() for p in mdir.iterdir()}
    calls = []

    def model(messages, **kwargs):
        rows = json.loads(messages[-1]["content"])["items"]
        calls.append(rows)
        assert len(rows) <= 16
        # 响应故意重排；业务节点 ID 和 evidence 永远不需要模型重建。
        return json.dumps({"items": [{"id": r["id"], "text": "Synthetic translation"}
                                      for r in reversed(rows)]})

    progress = []
    with patch.object(translation.assistant, "_chat", side_effect=model):
        result = translation.translate_topic_map(
            mdir, "Synthetic", source, target="en", on_progress=lambda a, b: progress.append((a, b)))
    assert len(calls) == 2 and progress == [(0, 21), (16, 21), (21, 21)]
    expected = copy.deepcopy(source)
    expected["meeting_summary"] = "Synthetic translation"
    for topic in expected["topics"]:
        for obj in (topic, *topic["children"]):
            obj.update(title="Synthetic translation", summary="Synthetic translation")
    assert result["topic_map"] == expected
    sidecar = translation.topic_map_sidecar_path(mdir, "en")
    completed = sidecar.read_bytes()

    # 漏条目后最多重试一次；结构仍不完整时不得覆盖已完成的 sidecar。
    with patch.object(translation.assistant, "_chat", return_value='{"items":[]}') as mock:
        try:
            translation.translate_topic_map(mdir, "Synthetic", source, target="en")
            raise AssertionError("incomplete translation accepted")
        except translation.TranslationError:
            pass
        assert mock.call_count == 2
    assert sidecar.read_bytes() == completed
    for invalid in ("[]", "null", '"text"', '{"items":[{"id":true,"text":"bad"}]}'):
        with patch.object(translation.assistant, "_chat", return_value=invalid) as mock:
            try:
                translation._translate_topic_fields({"meeting_summary": "虚构摘要"}, "en")
                raise AssertionError("invalid translation accepted")
            except translation.TranslationError:
                pass
            assert mock.call_count == 2
    with patch.object(translation.assistant, "_chat", side_effect=["{}", '{"items":[{"id":0,"text":"Summary"}]}']) as mock:
        assert translation._translate_topic_fields({"meeting_summary": "虚构摘要"}, "en")["meeting_summary"] == "Summary"
        assert mock.call_count == 2

    cancelled = False
    def cancel_after_reply(*args, **kwargs):
        global cancelled
        cancelled = True
        return model(*args, **kwargs)
    with patch.object(translation.assistant, "_chat", side_effect=cancel_after_reply):
        try:
            translation.translate_topic_map(mdir, "Synthetic", source, target="en",
                                            should_cancel=lambda: cancelled)
            raise AssertionError("cancelled translation saved")
        except translation.TranslationCancelled:
            pass
    assert sidecar.read_bytes() == completed
    assert all((mdir / name).read_bytes() == data for name, data in original.items())

    job = job_store._new_job("translation", meeting="synthetic", target_language="en",
                             translation_artifact="topic_map", progress={"done": 0, "total": 21})
    job["status"] = "running"
    translations._translation_failed(job, translation.TranslationError("private model response"))
    projected = jobs._job_with_recovery(job)
    progress = projected["progress"]
    assert progress["phase"] == "translation"
    assert progress["failure"]["code"] == "TRANSLATION_INVALID_OUTPUT"
    assert progress["failure"]["technical"]["exception_type"] == "TranslationError"
    assert progress["failure"]["blocked_outputs"] == ["translation"]
    assert set(progress["failure"]["preserved_outputs"]) == {
        "transcript", "speaker_navigation", "final_minutes", "topic_map"}
    assert "private model response" not in json.dumps(projected)
    assert json.loads((Path(tmp) / "jobs" / f"{job['id']}.json").read_text())["status"] == "failed"

    # 旧版已持久化的 prepare/全产物 pending 也必须能正确投影。
    legacy = copy.deepcopy(job)
    legacy["progress"]["phase"] = "prepare"
    legacy["progress"]["phases"][0].update(id="prepare", label_key="progress.prepare")
    legacy["progress"]["available_outputs"] = {"transcript": "pending", "final_minutes": "pending"}
    repaired = jobs._job_with_recovery(legacy)["progress"]
    assert repaired["phase"] == "translation" and repaired["failure"]["blocked_outputs"] == ["translation"]
    assert repaired["available_outputs"]["final_minutes"] == "ready"

    # 列表投影期间另一线程新增任务；单次响应使用一致的任务集合快照。
    identity = jobs._job_content_type
    def add_during_projection(item):
        job_store.JOBS["arrived"] = {"id": "arrived", "kind": "translation", "status": "queued"}
        return identity(item)
    with patch.object(jobs, "_job_content_type", side_effect=add_during_projection):
        listed = jobs.list_jobs()["jobs"]
    assert [j["id"] for j in listed] == [job["id"]]
    assert "arrived" in job_store.JOBS

print("Translation recovery: stable nodes, bounded retries, cancellation, diagnostics and queue snapshots passed")
