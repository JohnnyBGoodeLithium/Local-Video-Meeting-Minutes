#!/usr/bin/env python3
"""结构化作业进度、失败合同、动态阶段与 legacy 回退。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "web"))

from job_progress import (SCHEMA, apply_event, attempt_history, initial_progress,  # noqa: E402
                          normalize_job_progress, parse_event, phase_ids_for)


def job(**values):
    base = {
        "id": "synthetic-job", "kind": "upload", "route": "video",
        "status": "queued", "created": 100.0, "started": None,
        "finished": None, "rc": None, "cmd": ["python", "video_minutes.py"],
    }
    base.update(values)
    return base


assert phase_ids_for(job(route="teams")) == [
    "prepare", "teams_alignment", "voice_draft", "visual_extraction",
    "visual_understanding", "final_minutes", "topic_map",
]
assert phase_ids_for(job(route="video")) == [
    "prepare", "speech_processing", "voice_draft", "visual_extraction",
    "visual_understanding", "final_minutes", "topic_map",
]
assert phase_ids_for(job(route="video", cmd=["python", "video_minutes.py", "--no-vl"])) == [
    "prepare", "speech_processing", "voice_draft", "visual_extraction",
    "final_minutes", "topic_map",
]
assert phase_ids_for(job(route="audio")) == [
    "prepare", "speech_processing", "final_minutes",
]
assert phase_ids_for(job(route="media_url"))[0] == "download"
assert phase_ids_for(job(kind="regen", route="audio")) == ["prepare", "final_minutes"]
assert phase_ids_for(job(kind="retranscribe", route="audio")) == [
    "retranscribe_prepare", "speech_processing", "final_minutes",
]

event = parse_event('[progress] {"phase":"visual_understanding","state":"running",'
                    '"done":12,"total":36,"unit":"pages"}')
assert event and event[0] == "progress" and event[1]["done"] == 12
assert parse_event("[meta] harmless status") is None
assert parse_event("[progress] not-json") is None

base_job = job(status="running", started=100.0)
progress = initial_progress(base_job, 100.0)
progress = apply_event(progress, "progress", {
    "phase": "visual_understanding", "state": "running",
    "done": 12, "total": 36, "unit": "pages",
}, 200.0)
progress = apply_event(progress, "output_ready", {
    "output": "visuals", "state": "partial",
}, 201.0)
assert progress["schema"] == SCHEMA
assert progress["available_outputs"]["visuals"] == "partial"
assert progress["phases"][4]["state"] == "running"

eta_job = {**base_job, "progress": progress}
projected = normalize_job_progress(eta_job, (), now=320.0)
assert projected["estimated_remaining"]
assert projected["estimated_remaining"]["low_seconds"] >= 60
assert projected["estimated_remaining"]["high_seconds"] \
    > projected["estimated_remaining"]["low_seconds"]

waiting = apply_event(progress, "progress", {
    "phase": "visual_understanding", "state": "waiting_resource",
    "done": 12, "total": 36, "unit": "pages",
}, 321.0)
assert normalize_job_progress({**base_job, "progress": waiting}, (), now=500.0)[
    "estimated_remaining"] is None

done_progress = apply_event(progress, "phase_done", {
    "phase": "visual_understanding", "done": 36, "total": 36, "unit": "pages",
}, 400.0)
assert done_progress["phases"][4]["elapsed_seconds"] == 200.0

categories = (
    "input_invalid", "resource_insufficient", "service_unavailable",
    "capability_missing", "stage_processing_failed", "revision_conflict",
    "download_or_network_failed", "cancelled_or_paused", "unknown_internal",
)
for category in categories:
    failed = apply_event(initial_progress(base_job, 100.0), "failure", {
        "phase": "prepare", "code": category.upper(), "category": category,
        "recoverability": "resume_from_checkpoint", "done": 2, "total": 8,
        "exception_type": "SyntheticError", "private": "/secret/meeting.vtt",
    }, 150.0)
    failed_job = {**base_job, "status": "failed", "finished": 150.0,
                  "progress": failed}
    result = normalize_job_progress(failed_job, (), recovery={
        "state": "available", "action": "resume_from_assets", "scope": "minutes",
        "high_quality_available": False,
    }, now=150.0)
    failure = result["failure"]
    assert failure["category"] == category
    assert failure["diagnostic_id"].startswith("ERR-")
    assert failure["retry_options"][0]["reuses_existing_outputs"] is True
    assert "/secret" not in json.dumps(failure)

blocked = apply_event(initial_progress(base_job, 100.0), "failure", {
    "phase": "prepare", "code": "BAD_INPUT", "category": "input_invalid",
    "recoverability": "requires_user_action",
}, 150.0)
blocked = normalize_job_progress({**base_job, "status": "failed", "progress": blocked}, (),
                                 recovery={"state": "manual"}, now=150.0)
assert blocked["failure"]["recommended_action"] == "replace_input"

legacy = normalize_job_progress(job(
    kind="translation", status="running", stage="翻译逐字稿",
    progress={"done": 7, "total": 20}, started=100.0), (), now=120.0)
assert legacy["source"] == "legacy_estimate"
assert legacy["done"] == 7 and legacy["total"] == 20

degraded = initial_progress(job(kind="topic_map"), 100.0)
degraded = apply_event(degraded, "progress", {
    "phase": "topic_map", "state": "degraded",
}, 120.0)
degraded = normalize_job_progress(job(
    kind="topic_map", status="done", progress=degraded, finished=130.0), (), now=130.0)
assert degraded["state"] == "degraded"

voice_only = initial_progress(job(kind="regen", route="video",
                                  cmd=["python", "minutes_by_page.py", "--no-vl"]), 100.0)
voice_only = normalize_job_progress(job(
    kind="regen", route="video", status="done", degraded_requested=True,
    progress=voice_only, finished=130.0), (), now=130.0)
assert voice_only["state"] == "degraded"
assert voice_only["available_outputs"]["visuals"] == "skipped"
assert voice_only["degradation"]["code"] == "VOICE_ONLY_RESULT"

first = job(id="first", status="failed", recovered_by="second", finished=130.0)
first["progress"] = apply_event(initial_progress(first, 100.0), "failure", {
    "phase": "visual_understanding", "code": "VISUAL_STOPPED",
    "category": "service_unavailable", "recoverability": "resume_from_checkpoint",
    "done": 12, "total": 36,
}, 130.0)
second = job(id="second", status="running", retry_of="first", recovery_attempt=1,
             started=140.0)
second["progress"] = apply_event(initial_progress(second, 140.0), "progress", {
    "phase": "visual_understanding", "state": "recovering", "done": 18, "total": 36,
}, 150.0)
history = attempt_history(second, [first, second])
assert [item["attempt"] for item in history] == [1, 2]
assert history[0]["failure"]["code"] == "VISUAL_STOPPED"
assert "id" not in history[0]

print("Job progress: schema, plans, ETA, failures, degradation, and fallback passed")
