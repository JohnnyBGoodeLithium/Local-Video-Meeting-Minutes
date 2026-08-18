"""上传与作业队列：/api/upload 与 /api/jobs*。
服务 schema：作业 JSON 元数据（无版本字段；不含正文）。"""

import os
import re
import shutil
import signal
import threading
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

import meeting_dir as md_util
from deps import (AUDIO_EXT, BANK_LOCK, DATA_ROOT, DOCX_EXT, INBOX, PY, ROOT,
                  VIDEO_EXT, VTT_EXT, _now, _safe, _slugify)
from job_store import EXEC, JOBS, PROCS, _new_job, _run_pipeline, _save_job, _set_status
from job_recovery import (build_minutes_command, build_retranscribe_command,
                          build_topic_map_command, meeting_dir_for_job, recovery_plan)

router = APIRouter()


def _job_with_recovery(original: dict) -> dict:
    """给失败卡片附加有限恢复状态，不暴露判断所用日志正文或文件路径。"""
    job = dict(original)
    if job.get("status") not in {"failed", "cancelled"}:
        return job
    plan = recovery_plan(job)
    successor = JOBS.get(str(job.get("recovered_by") or ""))
    if successor and successor.get("status") in {"queued", "running", "done"}:
        plan = {**plan, "state": "recovered", "action": "none",
                "successor_status": successor.get("status")}
    job["recovery"] = plan
    return job


def _link_recovery(source: dict, successor: dict, quality: str) -> None:
    with BANK_LOCK:
        source["recovered_by"] = successor["id"]
        source["recovery_requested_at"] = _now()
        successor["retry_of"] = source["id"]
        successor["recovery_attempt"] = int(source.get("recovery_attempt") or 0) + 1
        successor["recovery_quality"] = quality
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
                 ignore_transcript: str = Form("")):
    if not files:
        raise HTTPException(400, "没有文件")
    skip_vl = bool(no_vl.strip())
    ignore_external = bool(ignore_transcript.strip())
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
    except Exception:
        # 校验中途失败不留下半上传目录。
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise

    cmd = [str(PY), str(ROOT / "bin" / script), *args]
    job = _new_job("upload", route=route, cmd=cmd,
                   files=[p.name for p in saved],
                   inbox=str(dest_dir.relative_to(DATA_ROOT)),
                   meeting=_predict_meeting(
                       route, primary, transcript,
                       prefer_transcript_title=ignore_external and transcript is not None),
                   transcript_policy=("ignored" if transcript is not None and ignore_external
                                      else "external" if transcript is not None else "local_asr"))
    resp = dict(job)  # 快照：避免 worker 线程抢在响应序列化前改状态
    EXEC.submit(_run_pipeline, job)
    return resp


@router.get("/api/jobs")
def list_jobs():
    queue = {item["id"]: item for item in EXEC.snapshot()}
    jobs = []
    for original in JOBS.values():
        job = _job_with_recovery(original)
        if job.get("status") == "running":
            job["queue_position"] = 0
        elif job.get("status") == "queued" and job["id"] in queue:
            job["queue_position"] = queue[job["id"]]["position"]
            job["queue_priority"] = queue[job["id"]]["priority"]
        jobs.append(job)
    return {
        "jobs": sorted(jobs, key=lambda j: j["created"], reverse=True),
        "capabilities": {"job_priority": True, "running_preemption": False,
                         "job_recovery": True},
        "queue_policy": ["用户优先", "会议处理", "纪要与脉络", "逐字稿翻译"],
    }


@router.get("/api/jobs/{jid}")
def get_job(jid: str):
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "没有这条作业")
    return _job_with_recovery(job)


@router.post("/api/jobs/{jid}/retry")
def retry_job(jid: str, quality: str = Query("standard", pattern="^(standard|high)$")):
    """从已保留资产恢复失败阶段；绝不直接重放作业 JSON 中的旧命令。"""
    source = JOBS.get(jid)
    if not source:
        raise HTTPException(404, "没有这条作业")
    if source.get("status") not in {"failed", "cancelled"}:
        raise HTTPException(409, "只有失败或已取消的任务可以恢复")
    plan = recovery_plan(source)
    if plan.get("state") != "available":
        raise HTTPException(409, "现有资产不足以安全续跑，请按卡片提示重新导入")
    if quality == "high" and not plan.get("high_quality_available"):
        raise HTTPException(409, "当前没有配置高质量恢复模型")

    successor = JOBS.get(str(source.get("recovered_by") or ""))
    if successor and successor.get("status") in {"queued", "running", "done"}:
        raise HTTPException(409, "这条失败任务已经恢复，无需重复提交")
    slug = str(source.get("meeting") or "")
    mdir = meeting_dir_for_job(source)
    if mdir is None:
        raise HTTPException(409, "会议资产已经不存在，请重新导入")

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
                kind = "regen"
            elif mode == "topic_map":
                command = build_topic_map_command(mdir)
                kind = "topic_map"
            elif mode == "retranscribe":
                command = build_retranscribe_command(mdir)
                kind = "retranscribe"
            else:
                raise ValueError("unsupported_recovery")
        except ValueError as exc:
            raise HTTPException(409, "会议资产已经变化，当前无法继续恢复") from exc
        new_job = _new_job(kind, meeting=slug, cmd=command,
                           recovery_scope=plan.get("scope"))
        EXEC.submit(_run_pipeline, new_job)

    _link_recovery(source, new_job, quality)
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
    proc = PROCS.get(jid)
    if proc and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

        def _hard_kill(p=proc):
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        threading.Timer(5.0, _hard_kill).start()
    _set_status(job, "cancelled", finished=_now())
    return {"ok": True}
