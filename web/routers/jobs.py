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
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

import meeting_dir as md_util
from deps import (AUDIO_EXT, BANK_LOCK, DATA_ROOT, INBOX, PY, ROOT, VIDEO_EXT,
                  VTT_EXT, _now, _safe, _slugify)
from job_store import EXEC, JOBS, PROCS, _new_job, _run_pipeline, _save_job, _set_status

router = APIRouter()


def _predict_meeting(route: str, primary: Path, vtt: Path | None) -> str:
    if route == "audio":
        return md_util.for_recording(DATA_ROOT, primary.stem, None).name
    date_m = re.search(r"(\d{8})", primary.name)
    stem = vtt.stem if (route == "teams" and vtt is not None) else primary.stem
    return md_util.for_teams(DATA_ROOT, _slugify(stem),
                             date_m.group(1) if date_m else "").name


@router.post("/api/upload")
async def upload(files: list[UploadFile] = File(...), no_vl: str = Form("")):
    if not files:
        raise HTTPException(400, "没有文件")
    skip_vl = bool(no_vl.strip())
    jid = uuid.uuid4().hex[:12]
    dest_dir = INBOX / jid
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    try:
        for f in files:
            ext = Path(f.filename or "").suffix.lower()
            if ext not in VIDEO_EXT | AUDIO_EXT | VTT_EXT:
                raise HTTPException(400, f"不支持的文件类型: {ext or f.filename}")
            dest = dest_dir / (_safe(Path(f.filename).stem) + ext)
            async with aiofiles.open(dest, "wb") as out:
                while chunk := await f.read(1 << 20):
                    await out.write(chunk)
            saved.append(dest)

        videos = [p for p in saved if p.suffix.lower() in VIDEO_EXT]
        vtts = [p for p in saved if p.suffix.lower() in VTT_EXT]
        audios = [p for p in saved if p.suffix.lower() in AUDIO_EXT]

        if len(videos) == 1 and not audios:
            vtt = next((v for v in vtts if v.stem == videos[0].stem),
                       vtts[0] if len(vtts) == 1 else None)
            if len(vtts) > 1 and vtt is None:
                raise HTTPException(400, "多个 VTT 无法确定与视频的配对关系")
            if vtt is not None:
                route, script, args = "teams", "teams_minutes.py", [str(videos[0]), str(vtt)]
            else:
                route, script, args = "video", "video_minutes.py", [str(videos[0])]
            if skip_vl:
                args.append("--no-vl")
            primary = videos[0]
        elif not videos and len(audios) == 1 and not vtts:
            route, script, args = "audio", "run_all.py", [str(audios[0])]
            primary, vtt = audios[0], None
        else:
            raise HTTPException(400, "一次只支持一个视频(可配一个 vtt)或一个音频")
    except Exception:
        # 校验中途失败不留下半上传目录。
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise

    cmd = [str(PY), str(ROOT / "bin" / script), *args]
    job = _new_job("upload", route=route, cmd=cmd,
                   files=[p.name for p in saved],
                   inbox=str(dest_dir.relative_to(DATA_ROOT)),
                   meeting=_predict_meeting(route, primary, vtt))
    resp = dict(job)  # 快照：避免 worker 线程抢在响应序列化前改状态
    EXEC.submit(_run_pipeline, job)
    return resp


@router.get("/api/jobs")
def list_jobs():
    queue = {item["id"]: item for item in EXEC.snapshot()}
    jobs = []
    for original in JOBS.values():
        job = dict(original)
        if job.get("status") == "running":
            job["queue_position"] = 0
        elif job.get("status") == "queued" and job["id"] in queue:
            job["queue_position"] = queue[job["id"]]["position"]
            job["queue_priority"] = queue[job["id"]]["priority"]
        jobs.append(job)
    return {
        "jobs": sorted(jobs, key=lambda j: j["created"], reverse=True),
        "capabilities": {"job_priority": True, "running_preemption": False},
        "queue_policy": ["用户优先", "会议处理", "纪要与脉络", "逐字稿翻译"],
    }


@router.get("/api/jobs/{jid}")
def get_job(jid: str):
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "没有这条作业")
    return job


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
