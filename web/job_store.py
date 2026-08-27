"""作业存储与调度：JOBS/PROCS 状态、作业 JSON 持久化、bin/ 管线 runner。

依赖 deps（路径常量与锁），不依赖 routers；server.py 启动时调用 load_jobs()。
"""

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from deps import (BANK_LOCK, CONTENT_TYPES, DATA_ROOT, DRY_RUN, DRY_RUN_DELAY, INBOX, JOBS_DIR,
                  MEETINGS, MEETING_META_LOCK, ROOT, _now)
from job_scheduler import SerialPriorityExecutor, default_priority

EXEC = SerialPriorityExecutor()  # 重模型仍单 worker 串行，但等待任务可以重排
JOBS: dict[str, dict] = {}
PROCS: dict[str, subprocess.Popen] = {}   # 运行中作业的子进程(取消用, 不序列化)

_CHILD_EXCEPTION_RE = re.compile(
    r"^(?:[A-Za-z_]\w*\.)*(?P<kind>[A-Za-z_]\w*(?:Error|Exception))(?::|$)")


def _safe_child_exception(line: str) -> str | None:
    """从 traceback 末行只保留异常类；消息可能含私有正文或路径，永不落盘。"""
    match = _CHILD_EXCEPTION_RE.match(str(line or "").strip())
    return f"[error] 子进程异常 ({match.group('kind')})" if match else None


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


def _record_meeting_activity(job: dict) -> None:
    """把会议的导入/更新时间固化到 meta.json。

    源媒体保留原始 mtime，不能用它推断「什么时候进入本应用」。
    imported_at 只在首次成功导入时写入；updated_at 记录最近一次会议派生资产成功更新。
    """
    slug = str(job.get("meeting") or "")
    mdir = (MEETINGS / slug).resolve()
    if not slug or mdir.parent != MEETINGS.resolve() or not mdir.is_dir():
        return
    meta_path = mdir / "meta.json"
    with MEETING_META_LOCK:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) \
                if meta_path.is_file() else {}
        except Exception:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        timestamp = float(job.get("finished") or _now())
        if job.get("kind") == "upload":
            meta.setdefault("imported_at", float(job.get("created") or timestamp))
            # 上传时选择的内容类型随首次成功导入固化；缺省/未知值保持缺省 meeting。
            ctype = str(job.get("content_type") or "")
            if ctype in CONTENT_TYPES:
                meta["content_type"] = ctype
        meta["updated_at"] = timestamp
        tmp = meta_path.with_name(f".{meta_path.name}.tmp-{os.getpid()}")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, meta_path)


def _scheduler_error(job: dict, exc: Exception) -> None:
    """未知异常不能杀死唯一调度线程；日志只保存异常类型，不保存潜在正文。"""
    job.setdefault("log", []).append(f"[error] 后台调度异常 ({type(exc).__name__})")
    _set_status(job, "failed", finished=_now(), rc=None)


EXEC.set_error_handler(_scheduler_error)


def _apply_job_result(job: dict) -> None:
    """读取受控子进程结果，只允许回填 meeting slug 等无正文元数据。"""
    rel = str(job.get("result_file") or "")
    if not rel:
        return
    path = (DATA_ROOT / rel).resolve()
    if not path.is_file() or not path.is_relative_to(INBOX.resolve()):
        return
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    meeting = str(result.get("meeting") or "").strip() if isinstance(result, dict) else ""
    if not meeting or Path(meeting).name != meeting:
        return
    mdir = (MEETINGS / meeting).resolve()
    if mdir.parent != MEETINGS.resolve() or not mdir.is_dir():
        return
    with BANK_LOCK:
        job["meeting"] = meeting
        _save_job(job)


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
        (("等待计算资源", "resource guard", "memory guard"), "等待计算资源"),
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
                safe_error = _safe_child_exception(line)
                if safe_error:
                    with BANK_LOCK:
                        if not job.setdefault("log", []) or job["log"][-1] != safe_error:
                            job["log"].append(safe_error)
                            job["log"] = job["log"][-300:]
                            _save_job(job)
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
    _apply_job_result(job)
    if proc.returncode != 0 and not job.get("cancel_requested"):
        # 作业 JSON 是可由 API 读取的元数据，不落模型输入/输出或任意 stderr 正文。
        job["log"].append(f"[error] 子进程失败 (rc={proc.returncode})")
    job["log"] = job["log"][-300:]
    if job.get("cancel_requested"):
        stopped_status = "paused" if job.get("pause_requested") else "cancelled"
        _set_status(job, stopped_status, finished=_now(), rc=proc.returncode)
    else:
        if proc.returncode == 0 and (job.get("kind") == "upload"
                                     or job.get("auto_resume")) and not DRY_RUN:
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
        finished = _now()
        _set_status(job, "done" if succeeded else "failed",
                    finished=finished, rc=proc.returncode,
                    result={"dry_run": True} if DRY_RUN and succeeded else None)
        if succeeded and not DRY_RUN and job.get("kind") in {
                "upload", "regen", "topic_map", "retranscribe"}:
            try:
                _record_meeting_activity(job)
            except Exception as exc:
                with BANK_LOCK:
                    job["log"].append(
                        f"[error] 会议时间元数据更新失败 ({type(exc).__name__})")
                    _save_job(job)
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
            # 关键字同样是低优先级派生作业；触发失败不影响主作业状态。
            try:
                from routers.keywords import auto_keywords_after_ready
                mdir = MEETINGS / str(job.get("meeting") or "")
                queued_kw = auto_keywords_after_ready(str(job.get("meeting") or ""), mdir) \
                    if mdir.is_dir() else []
                if queued_kw:
                    with BANK_LOCK:
                        job["log"].append("[meta] 已排队自动关键字提取")
                        _save_job(job)
            except Exception as exc:
                with BANK_LOCK:
                    job["log"].append(f"[error] 自动关键字触发失败 ({type(exc).__name__})")
                    _save_job(job)
