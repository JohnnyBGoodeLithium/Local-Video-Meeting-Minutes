"""向 Web 作业层发送脱敏、结构化的处理进度事件。

事件只允许稳定枚举、数字和短 key；不得携带正文、姓名、路径、URL、prompt 或模型输出。
普通 CLI 仍可保留 ``[meta]`` 日志，Web 只把本模块事件作为正式状态来源。
"""

from __future__ import annotations

import json
from typing import Iterable


PHASES = {
    "prepare", "download", "speech_processing", "teams_alignment", "voice_draft",
    "visual_extraction", "visual_understanding", "final_minutes", "topic_map",
    "retranscribe_prepare", "retrieval",
}
PHASE_STATES = {
    "pending", "running", "done", "waiting_resource", "paused", "failed",
    "degraded", "skipped", "cancelled", "recovering",
}
OUTPUTS = {
    "transcript", "speaker_navigation", "voice_draft", "visuals", "final_minutes",
    "topic_map", "retrieval",
}
UNITS = {"pages", "batches", "windows", "percent", "items"}
FAILURE_CATEGORIES = {
    "input_invalid", "resource_insufficient", "service_unavailable",
    "capability_missing", "stage_processing_failed", "revision_conflict",
    "download_or_network_failed", "cancelled_or_paused", "unknown_internal",
}
RECOVERABILITY = {
    "automatic", "resume_from_checkpoint", "retry_stage", "degraded_continue",
    "requires_user_action", "none",
}


def _safe_enum(value: str, allowed: set[str], name: str) -> str:
    text = str(value or "")
    if text not in allowed:
        raise ValueError(f"invalid_{name}")
    return text


def _count(value) -> int | None:
    if value is None:
        return None
    number = int(value)
    if number < 0 or number > 1_000_000:
        raise ValueError("invalid_count")
    return number


def _key(value: str | None, *, limit: int = 96) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or len(text) > limit or any(token in text for token in ("/", "\\", "?", "\n")):
        raise ValueError("invalid_key")
    return text


def _emit(kind: str, payload: dict) -> None:
    print(f"[{kind}] {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}",
          flush=True)


def progress(phase: str, *, state: str = "running", done: int | None = None,
             total: int | None = None, unit: str | None = None,
             message_key: str | None = None) -> None:
    payload = {
        "phase": _safe_enum(phase, PHASES, "phase"),
        "state": _safe_enum(state, PHASE_STATES, "state"),
    }
    if done is not None:
        payload["done"] = _count(done)
    if total is not None:
        payload["total"] = _count(total)
    if unit is not None:
        payload["unit"] = _safe_enum(unit, UNITS, "unit")
    if message_key is not None:
        payload["message_key"] = _key(message_key)
    _emit("progress", payload)


def phase_done(phase: str, *, done: int | None = None, total: int | None = None,
               unit: str | None = None) -> None:
    payload = {"phase": _safe_enum(phase, PHASES, "phase")}
    if done is not None:
        payload["done"] = _count(done)
    if total is not None:
        payload["total"] = _count(total)
    if unit is not None:
        payload["unit"] = _safe_enum(unit, UNITS, "unit")
    _emit("phase_done", payload)


def output_ready(output: str, *, state: str = "ready") -> None:
    output_states = {"ready", "partial"}
    _emit("output_ready", {
        "output": _safe_enum(output, OUTPUTS, "output"),
        "state": _safe_enum(state, output_states, "output_state"),
    })


def failure(code: str, category: str, phase: str, recoverability: str, *,
            done: int | None = None, total: int | None = None,
            exception_type: str | None = None) -> None:
    payload = {
        "code": _key(code, limit=64),
        "category": _safe_enum(category, FAILURE_CATEGORIES, "category"),
        "phase": _safe_enum(phase, PHASES, "phase"),
        "recoverability": _safe_enum(recoverability, RECOVERABILITY, "recoverability"),
    }
    if done is not None:
        payload["done"] = _count(done)
    if total is not None:
        payload["total"] = _count(total)
    if exception_type is not None:
        payload["exception_type"] = _key(exception_type, limit=80)
    _emit("failure", payload)


def recovery(action: str, phase: str, *, from_unit: int | None = None,
             reused: Iterable[str] = ()) -> None:
    allowed_actions = {"resume", "retry_stage", "degraded_continue", "restart"}
    payload = {
        "action": _safe_enum(action, allowed_actions, "action"),
        "phase": _safe_enum(phase, PHASES, "phase"),
        "reused": [_safe_enum(item, OUTPUTS, "output") for item in reused],
    }
    if from_unit is not None:
        payload["from_unit"] = _count(from_unit)
    _emit("recovery", payload)
