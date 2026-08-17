"""作业存储与调度：JOBS/PROCS 状态、作业 JSON 持久化、bin/ 管线 runner。

依赖 deps（路径常量与锁），不依赖 routers；server.py 启动时调用 load_jobs()。
"""

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from deps import (BANK_LOCK, DATA_ROOT, DRY_RUN, DRY_RUN_DELAY, INBOX, JOBS_DIR,
                  MEETINGS, ROOT, _now)
from job_scheduler import SerialPriorityExecutor, default_priority

EXEC = SerialPriorityExecutor()  # 重模型仍单 worker 串行，但等待任务可以重排
JOBS: dict[str, dict] = {}
PROCS: dict[str, subprocess.Popen] = {}   # 运行中作业的子进程(取消用, 不序列化)


# ---------------------------------------------------------------- 作业

def _job_path(jid: str) -> Path:
    return JOBS_DIR / f"{jid}.json"


def _save_job(job: dict):
    tmp = JOBS_DIR / f"{job['id']}.tmp"
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_job_path(job["id"]))


def _set_status(job: dict, status: str, **kw):
    with BANK_LOCK:
        job["status"] = status
        job.update(kw)
        _save_job(job)


def _scheduler_error(job: dict, exc: Exception) -> None:
    """未知异常不能杀死唯一调度线程；日志只保存异常类型，不保存潜在正文。"""
    job.setdefault("log", []).append(f"[error] 后台调度异常 ({type(exc).__name__})")
    _set_status(job, "failed", finished=_now(), rc=None)


EXEC.set_error_handler(_scheduler_error)


def _new_job(kind: str, **kw) -> dict:
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "kind": kind, "status": "queued", "created": _now(),
           "queue_priority": default_priority(kind), "priority_boost": False,
           "started": None, "finished": None, "rc": None, "log": [], **kw}
    with BANK_LOCK:
        JOBS[jid] = job
        _save_job(job)
    return job


def load_jobs():
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    for p in sorted(JOBS_DIR.glob("*.json")):
        try:
            job = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if job.get("status") in ("queued", "running"):
            job["status"] = "failed"
            job.setdefault("log", []).append("[error] 服务重启，作业中断")
            _save_job(job)
        JOBS[job["id"]] = job


def _pipeline_stage(line: str, current: str = "处理中") -> str:
    value = line.lower()
    stages = [
        (("语音草稿", "voice draft"), "生成语音草稿"),
        (("多模态纪要", "升级多模态", "补充屏幕资料"), "升级多模态纪要"),
        (("asr", "transcrib", "转写", "字幕"), "语音转写"),
        (("diar", "speaker", "发言人", "分离"), "区分发言人"),
        (("slide", "extract", "抽页", "抽屏幕", "逻辑页", "幻灯片"), "提取共享画面"),
        (("vl", "vision", "画面理解", "页面理解"), "理解共享画面"),
        (("minute", "summary", "纪要", "总结"), "生成纪要"),
        (("topic map", "会议脉络", "论点"), "构建会议脉络"),
        (("rag", "index", "索引", "检索"), "建立索引"),
    ]
    return next((label for needles, label in stages if any(needle in value for needle in needles)),
                current)


def _run_pipeline(job: dict):
    """后台线程：subprocess 调 bin/ 管线脚本。stdout 只留元数据行。"""
    if job.get("cancel_requested"):   # 排队期间被取消
        return
    _set_status(job, "running", started=_now(), stage="准备处理")
    cmd = job["cmd"]
    actual = [cmd[0], cmd[1], "--help"] if DRY_RUN else cmd
    if DRY_RUN:
        job["log"].append("[meta] dry-run 模式：仅执行 --help 校验脚本调用，未真正跑管线")
        if DRY_RUN_DELAY > 0:
            time.sleep(DRY_RUN_DELAY)
            if job.get("cancel_requested"):
                return
    try:
        proc = subprocess.Popen(
            actual, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env={**os.environ, "HF_HUB_OFFLINE": "1"},
            start_new_session=True)   # 独立进程组: 取消时整组杀(含管线拉起的孙进程)
        PROCS[job["id"]] = proc
        for raw in proc.stdout or []:
            line = raw.rstrip()
            if not line.lstrip().startswith("["):
                continue
            with BANK_LOCK:
                job.setdefault("log", []).append(line)
                job["log"] = job["log"][-300:]
                job["stage"] = _pipeline_stage(line, job.get("stage", "处理中"))
                _save_job(job)
        proc.wait()
    except Exception as e:
        job["log"].append(f"[error] 启动失败: {type(e).__name__}: {e}")
        _set_status(job, "failed", finished=_now(), rc=-1)
        return
    finally:
        PROCS.pop(job["id"], None)
    if proc.returncode != 0 and not job.get("cancel_requested"):
        # 作业 JSON 是可由 API 读取的元数据，不落模型输入/输出或任意 stderr 正文。
        job["log"].append(f"[error] 子进程失败 (rc={proc.returncode})")
    job["log"] = job["log"][-300:]
    if job.get("cancel_requested"):
        _set_status(job, "cancelled", finished=_now(), rc=proc.returncode)
    else:
        if proc.returncode == 0 and job.get("kind") == "upload" and not DRY_RUN:
            inbox_rel = str(job.get("inbox") or "")
            inbox_dir = (DATA_ROOT / inbox_rel).resolve()
            if inbox_rel and inbox_dir.is_dir() and inbox_dir.is_relative_to(INBOX.resolve()):
                try:
                    shutil.rmtree(inbox_dir)
                    job["inbox_cleaned"] = True
                    job["log"].append("[meta] 已清理处理完成的上传暂存目录")
                except OSError as exc:
                    job["inbox_cleaned"] = False
                    job["log"].append(f"[error] 上传暂存目录清理失败: {type(exc).__name__}")
        succeeded = proc.returncode == 0
        _set_status(job, "done" if succeeded else "failed",
                    finished=_now(), rc=proc.returncode,
                    result={"dry_run": True} if DRY_RUN and succeeded else None)
        if succeeded and not DRY_RUN and job.get("kind") in {"upload", "regen", "topic_map"}:
            # translations 路由依赖 job_store；这里只能运行时延迟导入，避免模块循环。
            # 自动补翻是低优先级附加作业，失败绝不能反向改坏主作业的 done 状态。
            try:
                from routers.translations import auto_translate_after_ready
                mdir = MEETINGS / str(job.get("meeting") or "")
                queued = auto_translate_after_ready(str(job.get("meeting") or ""), mdir) \
                    if mdir.is_dir() else []
                if queued:
                    with BANK_LOCK:
                        job["log"].append(f"[meta] 已排队自动翻译 {len(queued)} 项")
                        _save_job(job)
            except Exception as exc:
                with BANK_LOCK:
                    job["log"].append(f"[error] 自动翻译触发失败 ({type(exc).__name__})")
                    _save_job(job)
