"""`job-progress/v2` 正规化、动态阶段、失败合同和保守 ETA。

本模块只处理脱敏作业元数据。它不读取会议目录、正文、日志 traceback 或模型输出。
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import time
from copy import deepcopy
from typing import Iterable


SCHEMA = "job-progress/v2"
EVENT_RE = re.compile(r"^\[(progress|phase_done|output_ready|failure|recovery)\]\s+(\{.*\})$")
OUTPUTS = (
    "transcript", "speaker_navigation", "voice_draft", "visuals", "final_minutes",
    "topic_map", "retrieval",
)
VALID_PHASE_STATES = {
    "pending", "running", "done", "waiting_resource", "paused", "failed",
    "degraded", "skipped", "cancelled", "recovering",
}
VALID_JOB_STATES = {
    "queued", "running", "waiting_resource", "paused", "failed", "recovering",
    "degraded", "cancelled", "done",
}
VALID_FAILURE_CATEGORIES = {
    "input_invalid", "resource_insufficient", "service_unavailable",
    "capability_missing", "stage_processing_failed", "revision_conflict",
    "download_or_network_failed", "cancelled_or_paused", "unknown_internal",
}
VALID_OUTPUT_STATES = {"pending", "partial", "ready", "failed", "skipped"}
VALID_UNITS = {"pages", "batches", "windows", "percent", "items"}

PHASE_LABELS = {
    "prepare": "progress.prepare",
    "download": "progress.download",
    "speech_processing": "progress.speech_processing",
    "teams_alignment": "progress.teams_alignment",
    "voice_draft": "progress.voice_draft",
    "visual_extraction": "progress.visual_extraction",
    "visual_understanding": "progress.visual_understanding",
    "final_minutes": "progress.final_minutes",
    "topic_map": "progress.topic_map",
    "retranscribe_prepare": "progress.retranscribe_prepare",
    "retrieval": "progress.retrieval",
}


def _phase(phase_id: str) -> dict:
    return {
        "id": phase_id,
        "label_key": PHASE_LABELS[phase_id],
        "state": "pending",
        "started_at": None,
        "finished_at": None,
        "elapsed_seconds": None,
    }


def _has_arg(job: dict, value: str) -> bool:
    return value in [str(item) for item in job.get("cmd", [])]


def phase_ids_for(job: dict) -> list[str]:
    """按真实入口脚本和开关生成用户阶段，不显示未发生的检索构建。"""
    kind = str(job.get("kind") or "")
    route = str(job.get("route") or "")
    no_vl = _has_arg(job, "--no-vl")
    if kind == "translation":
        return ["prepare"]
    if kind == "photo_analysis":
        return ["visual_understanding", *(["final_minutes"]
                if job.get("sync_minutes") else [])]
    if kind == "topic_map":
        return ["prepare", "topic_map"]
    if kind == "retranscribe":
        # 内层 video/run_all 会继续发送实际阶段事件。
        if route == "audio":
            return ["retranscribe_prepare", "speech_processing", "final_minutes"]
        return ["retranscribe_prepare", "speech_processing", "voice_draft",
                "visual_understanding", "final_minutes", "topic_map"]
    if kind == "regen":
        reuse_visuals = _has_arg(job, "--reuse-vl-cache-only")
        skip_topic_map = _has_arg(job, "--skip-topic-map")
        if route == "audio":
            return ["prepare", "final_minutes"]
        return ["prepare", *([] if no_vl or reuse_visuals else ["visual_understanding"]),
                "final_minutes", *([] if skip_topic_map else ["topic_map"])]
    if route == "audio":
        return ["prepare", "speech_processing", "final_minutes"]
    if route == "teams":
        return ["prepare", "teams_alignment", "voice_draft", "visual_extraction",
                *([] if no_vl else ["visual_understanding"]), "final_minutes", "topic_map"]
    if route in {"video", "media_url"}:
        prefix = ["download"] if route == "media_url" else []
        return [*prefix, "prepare", "speech_processing", "voice_draft",
                "visual_extraction", *([] if no_vl else ["visual_understanding"]),
                "final_minutes", "topic_map"]
    return ["prepare"]


def initial_progress(job: dict, now: float | None = None) -> dict:
    now = float(now if now is not None else time.time())
    phases = [_phase(item) for item in phase_ids_for(job)]
    return {
        "schema": SCHEMA,
        "source": "structured",
        "route": str(job.get("route") or job.get("kind") or "unknown"),
        "state": "queued",
        "phase": phases[0]["id"] if phases else None,
        "phase_index": 0,
        "phase_count": len(phases),
        "phase_started_at": None,
        "started_at": None,
        "message_key": None,
        "done": None,
        "total": None,
        "unit": None,
        "available_outputs": {
            item: str((job.get("available_outputs") or {}).get(item) or "pending")
            for item in OUTPUTS
        },
        "estimated_first_usable": None,
        "estimated_remaining": None,
        "phases": phases,
        "failure": None,
        "attempt": max(1, int(job.get("recovery_attempt") or 0) + 1),
        "created_at": now,
    }


def parse_event(line: str) -> tuple[str, dict] | None:
    match = EVENT_RE.match(str(line or "").strip())
    if not match:
        return None
    try:
        value = json.loads(match.group(2))
    except (json.JSONDecodeError, TypeError):
        return None
    return (match.group(1), value) if isinstance(value, dict) else None


def _phase_by_id(progress: dict, phase_id: str) -> tuple[int, dict] | tuple[None, None]:
    for index, phase in enumerate(progress.get("phases", [])):
        if phase.get("id") == phase_id:
            return index, phase
    return None, None


def _safe_count(value):
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)) or value < 0 or value > 1_000_000:
        return None
    return value


def _safe_unit(value) -> str | None:
    text = str(value or "")
    return text if text in VALID_UNITS else None


def _copy_progress_units(target: dict, payload: dict) -> None:
    done = _safe_count(payload.get("done"))
    total = _safe_count(payload.get("total"))
    unit = _safe_unit(payload.get("unit"))
    if done is not None:
        target["done"] = done
    if total is not None:
        target["total"] = total
    if unit is not None:
        target["unit"] = unit


def _finish_phase(phase: dict, now: float) -> None:
    phase["state"] = "done"
    phase["finished_at"] = now
    if phase.get("started_at") is not None:
        phase["elapsed_seconds"] = max(0.0, now - float(phase["started_at"]))


def apply_event(progress: dict, kind: str, payload: dict,
                now: float | None = None) -> dict:
    now = float(now if now is not None else time.time())
    value = deepcopy(progress)
    if value.get("schema") != SCHEMA:
        return value
    if kind == "output_ready":
        output = str(payload.get("output") or "")
        if output in OUTPUTS:
            output_state = str(payload.get("state") or "ready")
            if output_state in VALID_OUTPUT_STATES:
                value["available_outputs"][output] = output_state
        return value
    phase_id = str(payload.get("phase") or "")
    index, phase = _phase_by_id(value, phase_id)
    if phase is None:
        return value
    if kind == "phase_done":
        if phase.get("started_at") is None:
            phase["started_at"] = now
        _copy_progress_units(phase, payload)
        _finish_phase(phase, now)
        value["phase"] = phase_id
        value["phase_index"] = index
        value["done"] = phase.get("done")
        value["total"] = phase.get("total")
        value["unit"] = phase.get("unit")
        return value
    if kind == "failure":
        phase["state"] = "failed"
        phase["finished_at"] = now
        _copy_progress_units(phase, payload)
        if phase.get("started_at") is not None:
            phase["elapsed_seconds"] = max(0.0, now - float(phase["started_at"]))
        value["state"] = "failed"
        value["phase"] = phase_id
        value["phase_index"] = index
        value["failure"] = _safe_failure(payload, phase_id, now)
        return value
    if kind == "recovery":
        phase["state"] = "recovering"
        phase["started_at"] = phase.get("started_at") or now
        value["state"] = "recovering"
        value["phase"] = phase_id
        value["phase_index"] = index
        value["recovery"] = {
            "action": str(payload.get("action") or "resume"),
            "from_unit": payload.get("from_unit"),
            "reused": [item for item in payload.get("reused", []) if item in OUTPUTS],
        }
        return value
    state = str(payload.get("state") or "running")
    if state not in VALID_PHASE_STATES:
        return value
    # A later phase implicitly closes prior running phases; it never marks untouched phases done.
    for prior in value.get("phases", [])[:index]:
        if prior.get("state") in {"running", "recovering"}:
            _finish_phase(prior, now)
    phase["state"] = state
    if state in {"running", "recovering", "waiting_resource"}:
        phase["started_at"] = phase.get("started_at") or now
    _copy_progress_units(phase, payload)
    message_key = str(payload.get("message_key") or "")
    if message_key and len(message_key) <= 96 \
            and re.fullmatch(r"[a-z0-9_.-]+", message_key):
        phase["message_key"] = message_key
    overall_state = state if state in {
        "waiting_resource", "recovering", "degraded", "paused", "cancelled",
    } else "running"
    value.update(
        state=overall_state,
        phase=phase_id,
        phase_index=index,
        phase_started_at=phase.get("started_at"),
        message_key=phase.get("message_key"),
        done=phase.get("done"), total=phase.get("total"), unit=phase.get("unit"),
    )
    return value


def _safe_failure(payload: dict, phase_id: str, now: float) -> dict:
    code = re.sub(r"[^A-Z0-9_]", "_", str(payload.get("code") or
                  "STAGE_PROCESSING_FAILED").upper())[:64]
    exception = re.sub(r"[^A-Za-z0-9_.]", "", str(payload.get("exception_type") or ""))[:80]
    digest = hashlib.sha256(f"{code}:{phase_id}:{int(now)}".encode()).hexdigest()[:6].upper()
    category = str(payload.get("category") or "stage_processing_failed")
    if category not in VALID_FAILURE_CATEGORIES:
        category = "unknown_internal"
    recoverability = str(payload.get("recoverability") or "retry_stage")
    if recoverability not in {
            "automatic", "resume_from_checkpoint", "retry_stage",
            "degraded_continue", "requires_user_action", "none"}:
        recoverability = "requires_user_action"
    return {
        "code": code,
        "category": category,
        "severity": str(payload.get("severity") or "blocking_current_stage"),
        "recoverability": recoverability,
        "title_key": f"failure.{code.lower()}.title",
        "explanation_key": f"failure.{code.lower()}.explanation",
        "impact_key": f"failure.{code.lower()}.impact",
        "failed_phase": phase_id,
        "failed_at": now,
        "completed_units": _safe_count(payload.get("done")),
        "total_units": _safe_count(payload.get("total")),
        "preserved_outputs": [],
        "blocked_outputs": [],
        "recommended_action": "resume_stage",
        "diagnostic_id": f"ERR-{digest}",
        "technical": {"exception_type": exception} if exception else {},
        "retry_options": [],
    }


def _legacy_phase(stage: str, phases: list[dict]) -> str:
    mapping = {
        "准备": "prepare", "下载": "download", "转写": "speech_processing",
        "发言人": "speech_processing", "语音草稿": "voice_draft",
        "提取共享画面": "visual_extraction", "理解共享画面": "visual_understanding",
        "生成纪要": "final_minutes", "升级多模态纪要": "final_minutes",
        "会议脉络": "topic_map", "索引": "retrieval",
    }
    found = next((phase for token, phase in mapping.items() if token in str(stage or "")), None)
    valid = {item["id"] for item in phases}
    return found if found in valid else (phases[0]["id"] if phases else "prepare")


def _legacy_progress(job: dict, now: float) -> dict:
    value = initial_progress(job, now)
    value["source"] = "legacy_estimate"
    phase_id = _legacy_phase(str(job.get("stage") or ""), value["phases"])
    index, phase = _phase_by_id(value, phase_id)
    state = str(job.get("status") or "queued")
    for prior in value["phases"][:index or 0]:
        prior["state"] = "done"
    phase["state"] = "running" if state == "running" else state if state in VALID_PHASE_STATES else "pending"
    phase["started_at"] = job.get("started")
    legacy_units = job.get("progress") if isinstance(job.get("progress"), dict) else {}
    done = legacy_units.get("done")
    total = legacy_units.get("total")
    if isinstance(done, (int, float)):
        phase["done"] = done
        value["done"] = done
    if isinstance(total, (int, float)):
        phase["total"] = total
        value["total"] = total
        phase["unit"] = "items"
        value["unit"] = "items"
    value.update(state=state if state in VALID_JOB_STATES else "failed", phase=phase_id,
                 phase_index=index or 0, started_at=job.get("started"),
                 phase_started_at=job.get("started"))
    return value


def _recent_phase_samples(job: dict, jobs: Iterable[dict], phase_id: str) -> list[float]:
    route = str(job.get("route") or job.get("kind") or "")
    values = []
    for item in jobs:
        progress = item.get("progress") if isinstance(item, dict) else None
        if item is job or item.get("status") != "done" or not isinstance(progress, dict):
            continue
        if str(progress.get("route") or "") != route:
            continue
        _index, phase = _phase_by_id(progress, phase_id)
        elapsed = phase.get("elapsed_seconds") if phase else None
        if isinstance(elapsed, (int, float)) and elapsed > 0:
            values.append(float(elapsed))
    return values[-5:]


def _eta(progress: dict, job: dict, jobs: Iterable[dict], now: float,
         *, until_phase: str | None = None) -> dict | None:
    if progress.get("state") not in {"running", "recovering"}:
        return None
    index, current = _phase_by_id(progress, str(progress.get("phase") or ""))
    if current is None:
        return None
    remaining = 0.0
    evidence = False
    done, total = current.get("done"), current.get("total")
    started = current.get("started_at")
    if isinstance(done, (int, float)) and isinstance(total, (int, float)) \
            and done >= 2 and total > done and started:
        remaining += max(0.0, (now - float(started)) / done * (total - done))
        evidence = True
    else:
        samples = _recent_phase_samples(job, jobs, current["id"])
        if samples:
            remaining += statistics.median(samples)
            evidence = True
    remaining_phases = progress.get("phases", [])[(index or 0) + 1:]
    if until_phase:
        cutoff = next((position for position, phase in enumerate(remaining_phases)
                       if phase.get("id") == until_phase), None)
        if cutoff is not None:
            remaining_phases = remaining_phases[:cutoff + 1]
    for phase in remaining_phases:
        if phase.get("state") not in {"pending", "recovering"}:
            continue
        samples = _recent_phase_samples(job, jobs, phase["id"])
        if samples:
            remaining += statistics.median(samples)
            evidence = True
    if not evidence or remaining < 60:
        return None
    return {
        "low_seconds": int(max(60, remaining * 0.8) // 60 * 60),
        "high_seconds": int(max(120, remaining * 1.35) // 60 * 60),
        "confidence": "medium" if done and done >= 2 else "low",
    }


def _infer_failure(job: dict, progress: dict, now: float) -> dict:
    rc = job.get("rc")
    stage = str(job.get("stage") or "")
    if rc in {-9, 137} or "资源" in stage:
        payload = {"code": "RESOURCE_INSUFFICIENT", "category": "resource_insufficient",
                   "recoverability": "resume_from_checkpoint"}
    elif rc in {-15, 130} or job.get("cancel_requested"):
        payload = {"code": "PROCESS_INTERRUPTED", "category": "cancelled_or_paused",
                   "recoverability": "resume_from_checkpoint"}
    else:
        payload = {"code": "STAGE_PROCESSING_FAILED", "category": "stage_processing_failed",
                   "recoverability": "retry_stage"}
    return _safe_failure(payload, str(progress.get("phase") or "prepare"),
                         float(job.get("finished") or now))


def _apply_recovery_contract(failure: dict, recovery: dict | None, outputs: dict) -> None:
    if not failure:
        return
    ready = [key for key, state in outputs.items() if state in {"ready", "partial"}]
    failure["preserved_outputs"] = ready
    failure["blocked_outputs"] = [key for key in OUTPUTS
                                   if outputs.get(key) == "pending"]
    if not recovery or recovery.get("state") != "available":
        failure["recommended_action"] = {
            "input_invalid": "replace_input",
            "resource_insufficient": "free_resources",
            "service_unavailable": "restore_service",
            "capability_missing": "change_provider",
            "revision_conflict": "review_latest_revision",
            "download_or_network_failed": "edit_source",
            "cancelled_or_paused": "resume_stage",
            "unknown_internal": "copy_diagnostics",
        }.get(str(failure.get("category") or ""), "resolve_or_reimport")
        return
    action = str(recovery.get("action") or "resume_from_assets")
    failure["recommended_action"] = action
    option = {
        "id": "resume_standard",
        "label_key": f"retry.{action}",
        "action": "resume",
        "scope": str(recovery.get("scope") or "stage"),
        "restart_from_unit": (failure.get("completed_units") or 0) + 1
            if failure.get("completed_units") is not None else None,
        "reuses_existing_outputs": True,
        "estimated_remaining": None,
        "enabled": True,
    }
    failure["retry_options"] = [option]
    if (failure.get("failed_phase") == "visual_understanding"
            and outputs.get("transcript") == "ready"):
        failure["retry_options"].append({
            "id": "finish_without_visuals",
            "label_key": "retry.finish_voice_only",
            "action": "degraded_continue",
            "scope": "minutes_without_remaining_visuals",
            "reuses_existing_outputs": True,
            "estimated_remaining": None,
            "enabled": True,
        })
    if recovery.get("high_quality_available"):
        failure["retry_options"].append({
            "id": "resume_high", "label_key": "retry.high_quality", "action": "resume_high",
            "scope": str(recovery.get("scope") or "stage"),
            "reuses_existing_outputs": True, "estimated_remaining": None, "enabled": True,
        })


def normalize_job_progress(job: dict, jobs: Iterable[dict] = (), *,
                           recovery: dict | None = None,
                           now: float | None = None) -> dict:
    now = float(now if now is not None else time.time())
    stored = job.get("progress")
    value = deepcopy(stored) if isinstance(stored, dict) and stored.get("schema") == SCHEMA \
        else _legacy_progress(job, now)
    status = str(job.get("status") or value.get("state") or "queued")
    if status == "done":
        degraded = bool(job.get("degraded_requested")) or any(
            phase.get("state") == "degraded" for phase in value.get("phases", []))
        value["state"] = "degraded" if degraded else "done"
        if job.get("degraded_requested"):
            value["degradation"] = {
                "code": "VOICE_ONLY_RESULT",
                "missing_outputs": ["visuals"],
            }
            value["available_outputs"]["visuals"] = "skipped"
        for phase in value.get("phases", []):
            if phase.get("state") in {"pending", "running", "recovering"}:
                phase["state"] = "done"
        inferred_outputs = {
            "upload": ("transcript", "speaker_navigation", "final_minutes"),
            "retranscribe": ("transcript", "speaker_navigation", "final_minutes"),
            "regen": ("final_minutes",),
            "topic_map": ("topic_map",),
        }.get(str(job.get("kind") or ""), ())
        for output in inferred_outputs:
            value["available_outputs"][output] = "ready"
    elif status in {"failed", "cancelled", "paused"}:
        value["state"] = status
        if status == "failed" and not value.get("failure"):
            value["failure"] = _infer_failure(job, value, now)
    elif status in VALID_JOB_STATES:
        if status != "running" or value.get("state") not in {
                "waiting_resource", "recovering", "degraded"}:
            value["state"] = status
    value["started_at"] = value.get("started_at") or job.get("started")
    value["attempt"] = max(1, int(job.get("recovery_attempt") or 0) + 1)
    value["estimated_remaining"] = _eta(value, job, jobs, now)
    outputs = value.get("available_outputs", {})
    first_ready = any(outputs.get(item) == "ready"
                      for item in ("transcript", "voice_draft", "final_minutes"))
    first_phase = "teams_alignment" if value.get("route") == "teams" \
        else "speech_processing" if value.get("route") in {"video", "media_url"} \
        else "final_minutes"
    value["estimated_first_usable"] = None if first_ready else _eta(
        value, job, jobs, now, until_phase=first_phase)
    _apply_recovery_contract(value.get("failure"), recovery, outputs)
    return value


def attempt_history(original: dict, jobs: Iterable[dict]) -> list[dict]:
    """把 retry 链投影为不含 job id、日志和私有内容的尝试历史。"""
    items = {str(item.get("id") or ""): item for item in jobs if isinstance(item, dict)}
    current = original
    visited = set()
    while current and current.get("retry_of") and str(current.get("id")) not in visited:
        visited.add(str(current.get("id")))
        current = items.get(str(current.get("retry_of") or ""))
    visited.clear()
    history = []
    while current and str(current.get("id")) not in visited:
        visited.add(str(current.get("id")))
        progress = normalize_job_progress(current, items.values())
        failure = progress.get("failure") or {}
        history.append({
            "attempt": len(history) + 1,
            "status": current.get("status"),
            "started_at": current.get("started"),
            "finished_at": current.get("finished"),
            "phase": progress.get("phase"),
            "done": progress.get("done"),
            "total": progress.get("total"),
            "failure": ({
                "code": failure.get("code"),
                "category": failure.get("category"),
                "diagnostic_id": failure.get("diagnostic_id"),
            } if failure else None),
        })
        current = items.get(str(current.get("recovered_by") or ""))
    return history
