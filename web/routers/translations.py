"""逐字稿/纪要/会议脉络/屏幕标题摘要翻译。
服务 schema：meeting-transcript-translation/v1、meeting-minutes-translation/v1、
meeting-topic-map-translation/v1、meeting-visuals-translation/v1。"""

from fastapi import APIRouter, HTTPException, Query

import meeting_topic_map
import meeting_generation
import translation_service as translation
from deps import (BANK_LOCK, DRY_RUN, assistant, _current_evidence,
                  _meeting_identity, _minutes_file, _minutes_reading_source,
                  _mdir, _now, _read_json, _render_minutes_language)
from job_store import EXEC, JOBS, _new_job, _save_job, _set_status
from job_progress import apply_event, initial_progress, normalize_job_progress

router = APIRouter()


def _translation_progress(job: dict, done: int, total: int) -> dict:
    stored = job.get("progress") or {}
    progress = stored if stored.get("schema") == "job-progress/v2" else initial_progress(job)
    return apply_event(progress, "progress", {
        "phase": "translation", "state": "running", "done": done,
        "total": total, "unit": "items"})


def _translation_failed(job: dict, exc: Exception, *, source_missing: bool = False) -> None:
    """保留可操作的失败类型；不记录模型输出、节点正文或供应商错误正文。"""
    unavailable = (isinstance(exc, assistant.AssistantUnavailable)
                   and not isinstance(exc, assistant.AssistantInvalidOutput))
    code = ("TRANSLATION_SOURCE_MISSING" if source_missing else
            "TRANSLATION_SERVICE_UNAVAILABLE" if unavailable else
            "TRANSLATION_INVALID_OUTPUT")
    now = _now()
    with BANK_LOCK:
        progress = normalize_job_progress(job, now=now)
        progress = apply_event(progress, "failure", {
            "phase": "translation", "code": code,
            "category": "input_invalid" if source_missing else
                        "service_unavailable" if unavailable else "stage_processing_failed",
            "recoverability": "retry_stage", "exception_type": type(exc).__name__,
            "done": progress.get("done"), "total": progress.get("total"),
        }, now)
        job.setdefault("log", []).append(f"[error] 翻译失败 ({code})")
    _set_status(job, "failed", finished=now, rc=None, progress=progress)


def _translation_payload(slug: str, mdir, target: str) -> dict:
    ident = _meeting_identity(slug)
    return translation.translation_payload(
        mdir, ident["title"], _current_evidence(mdir), target=target)


def _minutes_translation_payload(slug: str, mdir, target: str) -> dict:
    ident = _meeting_identity(slug)
    source, evidence = _minutes_reading_source(mdir)
    payload = translation.minutes_translation_payload(
        mdir, ident["title"], source, evidence, target=target)
    if payload.get("state") == "ready" and payload.get("markdown"):
        payload["html"] = _render_minutes_language(payload["markdown"], evidence, target)
    return payload


def _topic_map_translation_payload(slug: str, mdir, target: str) -> dict:
    state, topic_map = meeting_topic_map.load_current_topic_map(mdir)
    if state != "ready" or not topic_map:
        raise HTTPException(404, "没有可翻译的会议脉络")
    return translation.topic_map_translation_payload(mdir, topic_map, target=target)


def _visuals_translation_payload(mdir, target: str) -> dict:
    return translation.visuals_translation_payload(mdir, target=target)


def _run_translation(job: dict, mdir, title: str, target: str) -> None:
    """同一串行 worker 内执行本地翻译；作业日志只记录进度数字。"""
    if job.get("cancel_requested"):
        return
    target_label = translation.TARGETS[target]["label"]
    _set_status(job, "running", started=_now(), stage=f"生成{target_label}译文",
                progress=_translation_progress(job, 0, 0))

    def cancelled() -> bool:
        return bool(job.get("cancel_requested"))

    def progress(done: int, total: int) -> None:
        if cancelled():
            return
        with BANK_LOCK:
            job["progress"] = _translation_progress(job, done, total)
            job["log"] = [line for line in job.get("log", [])
                          if not line.startswith("[meta] 翻译进度")]
            job["log"].append(f"[meta] 翻译进度 {done}/{total}")
            _save_job(job)

    def priority_indexes() -> list[int]:
        return list(job.get("focus_turn_indexes", []))

    try:
        document = translation.translate_transcript(
            mdir, title, _current_evidence(mdir), dry_run=DRY_RUN,
            on_progress=progress, should_cancel=cancelled,
            priority_indexes=priority_indexes, target=target)
    except translation.TranslationCancelled:
        if job.get("status") != "cancelled":
            _set_status(job, "cancelled", finished=_now(), rc=None)
        return
    except (translation.TranslationError, assistant.AssistantError) as exc:
        if cancelled():
            if job.get("status") != "cancelled":
                _set_status(job, "cancelled", finished=_now(), rc=None)
        else:
            _translation_failed(job, exc)
        return
    if cancelled():
        if job.get("status") != "cancelled":
            _set_status(job, "cancelled", finished=_now(), rc=None)
        return
    _set_status(
        job, "done", finished=_now(), rc=0,
        result={"target_language": target, "translated": len(document.get("turns", [])),
                "total": document.get("total", 0), "dry_run": DRY_RUN})


def _run_minutes_translation(job: dict, mdir, title: str, target: str) -> None:
    if job.get("cancel_requested"):
        return
    target_label = translation.TARGETS[target]["label"]
    source, evidence = _minutes_reading_source(mdir)
    source_state = meeting_generation.document_state(mdir, bool(source))
    stage_label = (f"生成{target_label}语音草稿译文" if source_state == "draft"
                   else f"生成{target_label}纪要")
    _set_status(job, "running", started=_now(), stage=stage_label,
                translation_source_state=source_state,
                progress=_translation_progress(job, 0, 0))

    def cancelled() -> bool:
        return bool(job.get("cancel_requested"))

    def progress(done: int, total: int) -> None:
        if cancelled():
            return
        with BANK_LOCK:
            job["progress"] = _translation_progress(job, done, total)
            job["log"] = [line for line in job.get("log", [])
                          if not line.startswith("[meta] 纪要翻译进度")]
            job["log"].append(f"[meta] 纪要翻译进度 {done}/{total}")
            _save_job(job)

    try:
        document = translation.translate_minutes(
            mdir, title, source, evidence, dry_run=DRY_RUN, on_progress=progress,
            should_cancel=cancelled, target=target)
    except translation.TranslationCancelled:
        if job.get("status") != "cancelled":
            _set_status(job, "cancelled", finished=_now(), rc=None)
        return
    except (translation.TranslationError, assistant.AssistantError) as exc:
        _translation_failed(job, exc)
        return
    _set_status(job, "done", finished=_now(), rc=0,
                result={"target_language": target, "artifact": "minutes",
                        "source_state": source_state,
                        "done": document.get("done", 1), "total": document.get("total", 1),
                        "dry_run": DRY_RUN})


def _run_topic_map_translation(job: dict, mdir, title: str, target: str) -> None:
    if job.get("cancel_requested"):
        return
    state, topic_map = meeting_topic_map.load_current_topic_map(mdir)
    if state != "ready" or not topic_map:
        _translation_failed(job, translation.TranslationError("source missing"), source_missing=True)
        return
    target_label = translation.TARGETS[target]["label"]
    _set_status(job, "running", started=_now(), stage=f"生成{target_label}会议脉络",
                progress=_translation_progress(job, 0, 1))

    def cancelled() -> bool:
        return bool(job.get("cancel_requested"))

    def progress(done: int, total: int) -> None:
        with BANK_LOCK:
            if not cancelled():
                job["progress"] = _translation_progress(job, done, total)
                _save_job(job)

    try:
        translation.translate_topic_map(
            mdir, title, topic_map, dry_run=DRY_RUN,
            should_cancel=cancelled, target=target, on_progress=progress)
    except translation.TranslationCancelled:
        if job.get("status") != "cancelled":
            _set_status(job, "cancelled", finished=_now(), rc=None)
        return
    except (translation.TranslationError, assistant.AssistantError) as exc:
        _translation_failed(job, exc)
        return
    if cancelled():
        if job.get("status") != "cancelled":
            _set_status(job, "cancelled", finished=_now(), rc=None)
        return
    _set_status(job, "done", finished=_now(), rc=0,
                progress=_translation_progress(job, job["progress"]["total"], job["progress"]["total"]),
                result={"target_language": target, "artifact": "topic_map",
                        "dry_run": DRY_RUN})


def _run_visuals_translation(job: dict, mdir, target: str) -> None:
    if job.get("cancel_requested"):
        return
    target_label = translation.TARGETS[target]["label"]
    total = len(translation.visuals_source(mdir))
    _set_status(job, "running", started=_now(), stage=f"生成{target_label}屏幕标题",
                progress=_translation_progress(job, 0, total))

    def cancelled() -> bool:
        return bool(job.get("cancel_requested"))

    def progress(done: int, count: int) -> None:
        if cancelled():
            return
        with BANK_LOCK:
            job["progress"] = _translation_progress(job, done, count)
            job["log"] = [line for line in job.get("log", [])
                          if not line.startswith("[meta] 屏幕翻译进度")]
            job["log"].append(f"[meta] 屏幕翻译进度 {done}/{count}")
            _save_job(job)

    try:
        document = translation.translate_visuals(
            mdir, dry_run=DRY_RUN, on_progress=progress,
            should_cancel=cancelled, target=target)
    except translation.TranslationCancelled:
        if job.get("status") != "cancelled":
            _set_status(job, "cancelled", finished=_now(), rc=None)
        return
    except (translation.TranslationError, assistant.AssistantError) as exc:
        _translation_failed(job, exc)
        return
    _set_status(job, "done", finished=_now(), rc=0,
                progress=_translation_progress(job, len(document.get("pages", [])), total),
                result={"target_language": target, "artifact": "visuals",
                        "dry_run": DRY_RUN})


@router.get("/api/meetings/{slug}/translations/transcript")
def get_transcript_translation(
        slug: str, target: str = Query("zh-CN", pattern="^(zh-CN|en)$")):
    mdir = _mdir(slug)
    return _translation_payload(slug, mdir, target)


@router.post("/api/meetings/{slug}/translations/transcript")
def create_transcript_translation(
        slug: str, target: str = Query("zh-CN", pattern="^(zh-CN|en)$"), force: bool = False,
        focus: str = ""):
    mdir = _mdir(slug)
    if not (mdir / "transcript.spk.json").is_file():
        raise HTTPException(400, "没有逐字稿，无法翻译")
    total_turns = len(_read_json(mdir / "transcript.spk.json", []))
    focus_indexes = []
    if focus.strip():
        try:
            focus_indexes = sorted({int(value) for value in focus.split(",") if value.strip()})
        except ValueError as exc:
            raise HTTPException(400, "翻译优先轮次格式错误") from exc
        if len(focus_indexes) > 30 or any(index < 0 or index >= total_turns
                                          for index in focus_indexes):
            raise HTTPException(400, "翻译优先轮次已经失效")
    current = _translation_payload(slug, mdir, target)
    if current["state"] == "ready" and not force:
        return {"id": None, "kind": "translation", "status": "done", "cached": True,
                "meeting": slug, "target_language": target,
                "result": {"translated": current["translated"], "total": current["total"]}}
    existing = next((job for job in _translation_jobs()
                     if job.get("kind") == "translation" and job.get("meeting") == slug
                     and job.get("target_language") == target
                     and job.get("translation_artifact", "transcript") == "transcript"
                     and job.get("status") in {"queued", "running"}), None)
    if existing:
        if focus_indexes:
            with BANK_LOCK:
                combined = existing.get("focus_turn_indexes", []) + focus_indexes
                existing["focus_turn_indexes"] = list(dict.fromkeys(combined))[-30:]
                _save_job(existing)
        return dict(existing)
    job = _new_job("translation", meeting=slug, target_language=target,
                   translation_artifact="transcript",
                   focus_turn_indexes=focus_indexes,
                   progress={"done": len(current.get("turns", [])), "total": total_turns})
    response = dict(job)
    EXEC.submit(_run_translation, job, mdir, _meeting_identity(slug)["title"], target)
    return response


@router.get("/api/meetings/{slug}/translations/minutes")
def get_minutes_translation(
        slug: str, target: str = Query("zh-CN", pattern="^(zh-CN|en)$")):
    mdir = _mdir(slug)
    if _minutes_file(mdir) is None:
        raise HTTPException(404, "没有会议纪要")
    return _minutes_translation_payload(slug, mdir, target)


@router.post("/api/meetings/{slug}/translations/minutes")
def create_minutes_translation(
        slug: str, target: str = Query("zh-CN", pattern="^(zh-CN|en)$"), force: bool = False):
    mdir = _mdir(slug)
    if _minutes_file(mdir) is None:
        raise HTTPException(400, "没有会议纪要，无法翻译")
    current = _minutes_translation_payload(slug, mdir, target)
    if current["state"] == "ready" and not force:
        return {"id": None, "kind": "translation", "status": "done", "cached": True,
                "meeting": slug, "target_language": target, "translation_artifact": "minutes"}
    existing = next((job for job in _translation_jobs()
                     if job.get("kind") == "translation" and job.get("meeting") == slug
                     and job.get("target_language") == target
                     and job.get("translation_artifact") == "minutes"
                     and job.get("status") in {"queued", "running"}), None)
    if existing:
        return dict(existing)
    job = _new_job("translation", meeting=slug, target_language=target,
                   translation_artifact="minutes",
                   translation_source_state=meeting_generation.document_state(mdir, True),
                   progress={"done": 0, "total": 0})
    response = dict(job)
    EXEC.submit(_run_minutes_translation, job, mdir, _meeting_identity(slug)["title"], target)
    return response


@router.get("/api/meetings/{slug}/translations/topic-map")
def get_topic_map_translation(
        slug: str, target: str = Query("zh-CN", pattern="^(zh-CN|en)$")):
    mdir = _mdir(slug)
    return _topic_map_translation_payload(slug, mdir, target)


@router.post("/api/meetings/{slug}/translations/topic-map")
def create_topic_map_translation(
        slug: str, target: str = Query("zh-CN", pattern="^(zh-CN|en)$"), force: bool = False):
    mdir = _mdir(slug)
    current = _topic_map_translation_payload(slug, mdir, target)
    if current["state"] == "ready" and not force:
        return {"id": None, "kind": "translation", "status": "done", "cached": True,
                "meeting": slug, "target_language": target,
                "translation_artifact": "topic_map"}
    existing = next((job for job in _translation_jobs()
                     if job.get("kind") == "translation" and job.get("meeting") == slug
                     and job.get("target_language") == target
                     and job.get("translation_artifact") == "topic_map"
                     and job.get("status") in {"queued", "running"}), None)
    if existing:
        return dict(existing)
    job = _new_job("translation", meeting=slug, target_language=target,
                   translation_artifact="topic_map", progress={"done": 0, "total": 1})
    response = dict(job)
    EXEC.submit(_run_topic_map_translation, job, mdir, _meeting_identity(slug)["title"], target)
    return response


@router.get("/api/meetings/{slug}/translations/visuals")
def get_visuals_translation(
        slug: str, target: str = Query("zh-CN", pattern="^(zh-CN|en)$")):
    mdir = _mdir(slug)
    return _visuals_translation_payload(mdir, target)


@router.post("/api/meetings/{slug}/translations/visuals")
def create_visuals_translation(
        slug: str, target: str = Query("zh-CN", pattern="^(zh-CN|en)$"), force: bool = False):
    mdir = _mdir(slug)
    current = _visuals_translation_payload(mdir, target)
    if not current.get("total"):
        raise HTTPException(400, "没有可翻译的屏幕资料")
    if current["state"] == "ready" and not force:
        return {"id": None, "kind": "translation", "status": "done", "cached": True,
                "meeting": slug, "target_language": target,
                "translation_artifact": "visuals"}
    existing = _active_translation(slug, target, "visuals")
    if existing:
        return dict(existing)
    job = _new_job("translation", meeting=slug, target_language=target,
                   translation_artifact="visuals", progress={"done": current.get("translated", 0),
                                                                "total": current.get("total", 0)})
    response = dict(job)
    EXEC.submit(_run_visuals_translation, job, mdir, target)
    return response


def _translation_jobs() -> list[dict]:
    with BANK_LOCK:
        return list(JOBS.values())


def _active_translation(slug: str, target: str, artifact: str) -> dict | None:
    return next((job for job in _translation_jobs()
                 if job.get("kind") == "translation" and job.get("meeting") == slug
                 and job.get("target_language") == target
                 and job.get("translation_artifact", "transcript") == artifact
                 and job.get("status") in {"queued", "running"}), None)


def auto_translate_after_ready(slug: str, mdir) -> list[str]:
    """终稿就绪后低优先级补齐另一阅读语言；逐字稿明确不在自动范围。"""
    minutes_path = _minutes_file(mdir)
    if minutes_path is None or meeting_generation.document_state(mdir, True) != "ready":
        return []
    source, evidence = _minutes_reading_source(mdir)
    title = _meeting_identity(slug)["title"]
    queued = []
    retry_states = {"missing", "stale", "context_stale", "failed", "cancelled", "partial"}
    topic_state, topic_map = meeting_topic_map.load_current_topic_map(mdir)

    # 各资产的原文语言可以不同：英文会议的 VL 解读仍可能由
    # 本地模型输出中文。因此分别检查中/英两种阅读语言，每个 payload
    # 自己在“原文=目标语言”时短路，只会为真正缺失的方向建 sidecar。
    for target in ("zh-CN", "en"):
        minutes = translation.minutes_translation_payload(
            mdir, title, source, evidence, target=target)
        if (minutes.get("state") in retry_states
                and not _active_translation(slug, target, "minutes")):
            job = _new_job("translation", meeting=slug, target_language=target,
                           translation_artifact="minutes", auto=True,
                           progress={"done": minutes.get("done", 0),
                                     "total": minutes.get("total", 0)})
            EXEC.submit(_run_minutes_translation, job, mdir, title, target)
            queued.append(job["id"])

        if topic_state == "ready" and topic_map:
            topic_payload = translation.topic_map_translation_payload(
                mdir, topic_map, target=target)
            if (topic_payload.get("state") in retry_states
                    and not _active_translation(slug, target, "topic_map")):
                job = _new_job("translation", meeting=slug, target_language=target,
                               translation_artifact="topic_map", auto=True,
                               progress={"done": 0, "total": 1})
                EXEC.submit(_run_topic_map_translation, job, mdir, title, target)
                queued.append(job["id"])

        visuals = translation.visuals_translation_payload(mdir, target=target)
        if (visuals.get("total") and visuals.get("state") in retry_states
                and not _active_translation(slug, target, "visuals")):
            job = _new_job("translation", meeting=slug, target_language=target,
                           translation_artifact="visuals", auto=True,
                           progress={"done": visuals.get("translated", 0),
                                     "total": visuals.get("total", 0)})
            EXEC.submit(_run_visuals_translation, job, mdir, target)
            queued.append(job["id"])
    return queued
