"""上传与作业队列：/api/upload 与 /api/jobs*。
服务 schema：作业 JSON 元数据（无版本字段；不含正文）。"""

import json
import os
import re
import shutil
import signal
import threading
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

import meeting_dir as md_util
from deps import (AUDIO_EXT, BANK_LOCK, CONTENT_TYPES, DATA_ROOT, DOCX_EXT, INBOX, PY, ROOT,
                  VIDEO_EXT, VTT_EXT, _meeting_identity, _now, _safe, _slugify,
                  _video_path)
from job_store import EXEC, JOBS, PROCS, _new_job, _run_pipeline, _save_job, _set_status
from job_progress import apply_event, attempt_history, normalize_job_progress
from job_recovery import (build_minutes_command, build_retranscribe_command,
                          build_speaker_resume_command, build_topic_map_command,
                          meeting_dir_for_job, preemption_resume_spec, recovery_plan)
from media_url import MediaURLRejected, normalize_url_shape

router = APIRouter()


class MediaURLImport(BaseModel):
    url: str
    no_vl: bool = False


def _job_content_type(job: dict) -> str:
    explicit = str(job.get("content_type") or "")
    if explicit in CONTENT_TYPES:
        return explicit
    slug = str(job.get("meeting") or "")
    if slug:
        return str(_meeting_identity(slug).get("content_type") or "meeting")
    return "meeting"


def _job_with_recovery(original: dict) -> dict:
    """给失败卡片附加有限恢复状态，不暴露判断所用日志正文或文件路径。"""
    job = dict(original)
    job["content_type"] = _job_content_type(job)
    plan = None
    if job.get("status") in {"failed", "cancelled", "paused"}:
        plan = recovery_plan(job)
        successor = JOBS.get(str(job.get("recovered_by") or ""))
        if successor and successor.get("status") in {"queued", "running", "done"}:
            plan = {**plan, "state": "recovered", "action": "none",
                    "successor_status": successor.get("status")}
        job["recovery"] = plan
    job["progress"] = normalize_job_progress(job, JOBS.values(), recovery=plan)
    history = attempt_history(original, JOBS.values())
    if len(history) > 1:
        job["attempt_history"] = history
    return job


def _link_recovery(source: dict, successor: dict, quality: str) -> None:
    with BANK_LOCK:
        source["recovered_by"] = successor["id"]
        source["recovery_requested_at"] = _now()
        successor["retry_of"] = source["id"]
        successor["recovery_attempt"] = int(source.get("recovery_attempt") or 0) + 1
        successor["recovery_quality"] = quality
        if isinstance(successor.get("progress"), dict):
            successor["progress"]["attempt"] = successor["recovery_attempt"] + 1
            phase = str(successor["progress"].get("phase") or "prepare")
            successor["progress"] = apply_event(successor["progress"], "recovery", {
                "action": "resume", "phase": phase,
                "reused": [item for item in (source.get("progress") or {})
                           .get("available_outputs", {})
                           if (source.get("progress") or {})
                           .get("available_outputs", {}).get(item) == "ready"],
            })
        _save_job(source)
        _save_job(successor)


def _predict_meeting(route: str, primary: Path, transcript: Path | None,
                     *, prefer_transcript_title: bool = False) -> str:
    if route == "audio":
        return md_util.for_recording(DATA_ROOT, primary.stem, None).name
    date_m = re.search(r"(\d{8})", primary.name)
    stem = (transcript.stem if transcript is not None
            and (route == "teams" or prefer_transcript_title) else primary.stem)
    return md_util.for_teams(DATA_ROOT, _slugify(stem),
                             date_m.group(1) if date_m else "").name


@router.post("/api/upload")
async def upload(files: list[UploadFile] = File(...), no_vl: str = Form(""),
                 ignore_transcript: str = Form(""), content_type: str = Form("")):
    if not files:
        raise HTTPException(400, "没有文件")
    skip_vl = bool(no_vl.strip())
    ignore_external = bool(ignore_transcript.strip())
    content_type = content_type.strip() or "meeting"
    if content_type not in CONTENT_TYPES:
        raise HTTPException(400, "content_type 只支持 meeting 或 media")
    jid = uuid.uuid4().hex[:12]
    dest_dir = INBOX / jid
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    try:
        for f in files:
            ext = Path(f.filename or "").suffix.lower()
            if ext not in VIDEO_EXT | AUDIO_EXT | VTT_EXT | DOCX_EXT:
                raise HTTPException(400, f"不支持的文件类型: {ext or f.filename}")
            dest = dest_dir / (_safe(Path(f.filename).stem) + ext)
            async with aiofiles.open(dest, "wb") as out:
                while chunk := await f.read(1 << 20):
                    await out.write(chunk)
            saved.append(dest)

        videos = [p for p in saved if p.suffix.lower() in VIDEO_EXT]
        vtts = [p for p in saved if p.suffix.lower() in VTT_EXT]
        docx_files = [p for p in saved if p.suffix.lower() in DOCX_EXT]
        transcripts = [*vtts, *docx_files]
        audios = [p for p in saved if p.suffix.lower() in AUDIO_EXT]

        if len(videos) == 1 and not audios:
            if len(transcripts) > 1:
                raise HTTPException(400, "一次只能给视频配一个 VTT 或 DOCX 逐字稿")
            transcript = transcripts[0] if transcripts else None
            if transcript is not None and not ignore_external:
                route, script, args = ("teams", "teams_minutes.py",
                                       [str(videos[0]), str(transcript)])
            else:
                route, script, args = "video", "video_minutes.py", [str(videos[0])]
                if transcript is not None:
                    # 保留官方文件作为可回退源，但本次不解析它。
                    args += ["--slug", _slugify(transcript.stem),
                             "--ignored-transcript", str(transcript)]
            if skip_vl:
                args.append("--no-vl")
            primary = videos[0]
        elif not videos and len(audios) == 1 and not transcripts:
            route, script, args = "audio", "run_all.py", [str(audios[0])]
            primary, transcript = audios[0], None
        else:
            raise HTTPException(
                400, "一次只支持一个视频（可配一个 VTT/DOCX 逐字稿）或一个音频")
        if content_type == "media" and route != "video":
            raise HTTPException(400, "媒体模式只支持单个本地视频；会议录像与逐字稿请切回会议")
    except Exception:
        # 校验中途失败不留下半上传目录。
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise

    if route == "video" and content_type == "media":
        # 媒体视频走镜头检测抽帧；audio/teams 路由不受影响。
        args.append("--media")

    cmd = [str(PY), str(ROOT / "bin" / script), *args]
    job = _new_job("upload", route=route, cmd=cmd,
                   files=[p.name for p in saved],
                   inbox=str(dest_dir.relative_to(DATA_ROOT)),
                   meeting=_predict_meeting(
                       route, primary, transcript,
                       prefer_transcript_title=ignore_external and transcript is not None),
                   content_type=content_type,
                   processing_mode="fast" if skip_vl else "complete",
                   transcript_policy=("ignored" if transcript is not None and ignore_external
                                      else "external" if transcript is not None else "local_asr"))
    resp = dict(job)  # 快照：避免 worker 线程抢在响应序列化前改状态
    EXEC.submit(_run_pipeline, job)
    return resp


@router.post("/api/import-url")
def import_media_url(payload: MediaURLImport):
    """把公开视频链接排入 media 管线；原始 URL 不进入可读取的作业 JSON。"""
    try:
        url = normalize_url_shape(payload.url)
    except MediaURLRejected as exc:
        raise HTTPException(400, "请输入有效的 http/https 公公开视频链接") from exc

    jid = uuid.uuid4().hex[:12]
    dest_dir = INBOX / jid
    dest_dir.mkdir(parents=True, exist_ok=False)
    request_path = dest_dir / "media-url.request.json"
    result_path = dest_dir / "media-url.result.json"
    try:
        request_path.write_text(json.dumps({"url": url}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise

    command = [str(PY), str(ROOT / "bin" / "media_url.py"), str(request_path),
               "--result", str(result_path)]
    if payload.no_vl:
        command.append("--no-vl")
    host = (urlsplit(url).hostname or "公开视频").removeprefix("www.")
    job = _new_job(
        "upload", route="media_url", cmd=command, files=[],
        inbox=str(dest_dir.relative_to(DATA_ROOT)),
        result_file=str(result_path.relative_to(DATA_ROOT)),
        content_type="media", source_kind="url", display_name=f"链接媒体 · {host}",
        transcript_policy="local_asr",
        processing_mode="fast" if payload.no_vl else "complete")
    response = dict(job)
    EXEC.submit(_run_pipeline, job)
    return response


@router.get("/api/jobs")
def list_jobs():
    queue = {item["id"]: item for item in EXEC.snapshot()}
    jobs = []
    for original in JOBS.values():
        if original.get("hidden"):
            continue
        successor = JOBS.get(str(original.get("recovered_by") or ""))
        if successor is not None:
            # 一条恢复链在列表中只显示最后一次尝试；历史仍附在当前卡片中。
            continue
        job = _job_with_recovery(original)
        if job.get("status") == "running":
            job["queue_position"] = 0
            try:
                preemption_resume_spec(job)
            except ValueError:
                job["preemptible"] = False
            else:
                job["preemptible"] = True
        elif job.get("status") == "queued" and job["id"] in queue:
            job["queue_position"] = queue[job["id"]]["position"]
            job["queue_priority"] = queue[job["id"]]["priority"]
        jobs.append(job)
    return {
        "jobs": sorted(jobs, key=lambda j: j["created"], reverse=True),
        "capabilities": {"job_priority": True, "running_preemption": True,
                         "checkpointed_preemption": True,
                         "job_recovery": True, "job_hide": True,
                         "job_progress_v2": True, "attempt_history": True},
        "queue_policy": ["用户优先", "会议处理", "纪要与脉络", "逐字稿翻译"],
    }


@router.get("/api/jobs/{jid}")
def get_job(jid: str):
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "没有这条作业")
    return _job_with_recovery(job)


@router.post("/api/jobs/{jid}/retry")
def retry_job(jid: str, quality: str = Query("standard", pattern="^(standard|high)$"),
              strategy: str = Query("resume", pattern="^(resume|degraded)$")):
    """从已保留资产恢复失败阶段；绝不直接重放作业 JSON 中的旧命令。"""
    source = JOBS.get(jid)
    if not source:
        raise HTTPException(404, "没有这条作业")
    if source.get("status") not in {"failed", "cancelled", "paused"}:
        raise HTTPException(409, "只有失败、已取消或已暂停的任务可以恢复")
    plan = recovery_plan(source)
    if plan.get("state") != "available":
        raise HTTPException(409, "现有资产不足以安全续跑，请按卡片提示重新导入")
    if quality == "high" and not plan.get("high_quality_available"):
        raise HTTPException(409, "当前没有配置高质量恢复模型")
    if strategy == "degraded" and plan.get("mode") != "minutes":
        raise HTTPException(409, "当前失败阶段不能生成降级结果")

    successor = JOBS.get(str(source.get("recovered_by") or ""))
    if successor and successor.get("status") in {"queued", "running", "done"}:
        raise HTTPException(409, "这条失败任务已经恢复，无需重复提交")
    mdir = meeting_dir_for_job(source)
    if mdir is None:
        raise HTTPException(409, "会议资产已经不存在，请重新导入")
    # 旧上传任务可能保存了 p80 前预测出的短 slug；后续任务必须绑定到实际目录。
    slug = mdir.name

    mode = plan["mode"]
    if mode == "translation":
        # 调用现有翻译入队入口，让缓存/同资产并发规则继续保持单一实现。
        from routers import translations as translation_routes
        target = str(source.get("target_language") or "")
        artifact = str(source.get("translation_artifact") or "transcript")
        enqueue = {
            "transcript": translation_routes.create_transcript_translation,
            "minutes": translation_routes.create_minutes_translation,
            "topic_map": translation_routes.create_topic_map_translation,
            "visuals": translation_routes.create_visuals_translation,
        }[artifact]
        created = enqueue(slug, target=target, force=True)
        new_job = JOBS.get(str(created.get("id") or ""))
        if new_job is None:
            raise HTTPException(409, "译文已经可用，无需重试")
    else:
        if any(job.get("meeting") == slug and job.get("status") in {"queued", "running"}
               for job in JOBS.values()):
            raise HTTPException(409, "这场会议已有处理任务，请等待完成后再恢复")
        try:
            if mode == "minutes":
                refine = (os.environ.get("MEETING_RECOVERY_REFINE_MODEL", "").strip()
                          if quality == "high" else "")
                command = build_minutes_command(mdir, refine)
                if strategy == "degraded":
                    if not any(str(item).endswith("minutes_by_page.py") for item in command):
                        raise ValueError("degraded_not_applicable")
                    command.append("--no-vl")
                kind = "regen"
            elif mode == "topic_map":
                command = build_topic_map_command(mdir)
                kind = "topic_map"
            elif mode == "retranscribe":
                command = build_retranscribe_command(mdir)
                kind = "retranscribe"
            elif mode == "speaker_resume":
                command = build_speaker_resume_command(mdir)
                kind = "upload"
            else:
                raise ValueError("unsupported_recovery")
        except ValueError as exc:
            raise HTTPException(409, "会议资产已经变化，当前无法继续恢复") from exc
        new_job = _new_job(kind, route="video" if _video_path(mdir) else "audio",
                           meeting=slug, cmd=command,
                           recovery_scope=("minutes_without_visuals" if strategy == "degraded"
                                           else plan.get("scope")),
                           degraded_requested=strategy == "degraded")
        EXEC.submit(_run_pipeline, new_job)

    _link_recovery(source, new_job, "degraded" if strategy == "degraded" else quality)
    return _job_with_recovery(new_job)


@router.post("/api/jobs/{jid}/prioritize")
def prioritize_job(jid: str):
    """只置顶尚未开始的任务；运行中任务不抢占，避免损坏中间资产。"""
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "没有这条作业")
    if job.get("status") != "queued":
        raise HTTPException(409, "只有等待中的任务可以优先处理")
    if not EXEC.prioritize(jid):
        raise HTTPException(409, "任务已经开始，无法再调整顺序")
    with BANK_LOCK:
        job["priority_boost"] = True
        job["queue_priority"] = 0
        job["prioritized_at"] = _now()
        _save_job(job)
    queue = EXEC.snapshot()
    return {"ok": True, "id": jid,
            "queue_position": next((item["position"] for item in queue
                                    if item["id"] == jid), None)}


def _terminate_process_group(jid: str) -> None:
    proc = PROCS.get(jid)
    if not proc or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    def _hard_kill(p=proc):
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    threading.Timer(5.0, _hard_kill).start()


@router.post("/api/jobs/{jid}/force-prioritize")
def force_prioritize_job(jid: str):
    """暂停当前可恢复重任务，让等待中的急件先跑，随后自动续跑原任务。"""
    target = JOBS.get(jid)
    if not target:
        raise HTTPException(404, "没有这条作业")
    if target.get("status") != "queued":
        raise HTTPException(409, "只有等待中的任务可以立即处理")
    running = next((job for job in JOBS.values() if job.get("status") == "running"), None)
    if running is None:
        # 没有运行项时退化为普通置顶，不制造空暂停记录。
        return prioritize_job(jid)
    if running.get("meeting") == target.get("meeting"):
        raise HTTPException(409, "同一场会议已有任务运行，请等待该阶段完成")
    try:
        resume = preemption_resume_spec(running)
    except ValueError as exc:
        raise HTTPException(
            409, "当前任务尚未到可恢复检查点，不能强制让路；可先普通置顶") from exc
    proc = PROCS.get(str(running.get("id") or ""))
    if proc is None or proc.poll() is not None:
        raise HTTPException(409, "当前阶段正在切换，请稍后再点立即处理")
    if not EXEC.prioritize(jid):
        raise HTTPException(409, "急件已经开始，无法再调整顺序")

    now = _now()
    with BANK_LOCK:
        target["priority_boost"] = True
        target["queue_priority"] = 0
        target["forced_after"] = running["id"]
        target["prioritized_at"] = now
        running["cancel_requested"] = True
        running["pause_requested"] = True
        running["preempted_by"] = target["id"]
        running["paused_at"] = now
        _save_job(target)
        _save_job(running)

    # 自动续跑与急件同属用户优先级，但急件已被 prioritize 为负 sequence，
    # 因而一定先运行；续跑随后排在普通 upload/translation 之前。
    successor = _new_job(
        resume["kind"], meeting=resume["meeting"], cmd=resume["cmd"],
        recovery_scope=resume["scope"], queue_priority=0,
        priority_boost=True, auto_resume=True, resume_after=target["id"],
        inbox=running.get("inbox"))
    EXEC.submit(_run_pipeline, successor)
    _link_recovery(running, successor, "standard")
    _set_status(running, "paused", finished=now, rc=None)
    _terminate_process_group(running["id"])
    queue = EXEC.snapshot()
    return {"ok": True, "id": target["id"], "paused": running["id"],
            "resume_job": successor["id"],
            "queue_position": next((item["position"] for item in queue
                                    if item["id"] == target["id"]), None)}


@router.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str):
    """取消作业：排队的直接作废；运行中的整进程组 SIGTERM(5s 不死再 SIGKILL)。"""
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "没有这条作业")
    if job["status"] not in ("queued", "running"):
        raise HTTPException(400, f"作业已结束({job['status']})")
    was_queued = job["status"] == "queued"
    job["cancel_requested"] = True
    if was_queued:
        EXEC.discard(jid)
    _terminate_process_group(jid)
    _set_status(job, "cancelled", finished=_now())
    return {"ok": True}


@router.post("/api/jobs/{jid}/hide")
def hide_job(jid: str):
    """隐藏已结束的任务卡；只改作业元数据，不删除会议或失败现场。"""
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "没有这条作业")
    if job.get("status") in {"queued", "running"}:
        raise HTTPException(409, "正在处理的任务请先取消")
    with BANK_LOCK:
        job["hidden"] = True
        job["hidden_at"] = _now()
        _save_job(job)
    return {"ok": True}
