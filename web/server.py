#!/usr/bin/env python3
"""会议纪要本机 Web 服务（FastAPI，只 bind 127.0.0.1:8899，内容不出机器）。

启动（在 meeting-minutes/ 下）：
    .venv/bin/python web/server.py

环境变量（一般不用动）：
    MEETING_DATA_ROOT      私有数据根（默认项目根；测试可指向一次性目录）
    MEETING_WEB_BANK       声纹库目录（默认 DATA_ROOT/speaker_bank）
    MEETING_WEB_JOBS       作业 JSON 目录（默认 web/jobs）
    MEETING_WEB_DRYRUN=1   作业干跑模式：管线只执行 `<脚本> --help` 校验调用链，
                           regen 直接标记完成（供冒烟测试，不碰 GPU 模型）

隐私约定：stdout/作业日志只保留管线脚本的元数据行（以 "[" 开头的进度行），
不写任何转写/纪要正文。作业 json 只存元数据。
"""

import json
import mimetypes
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import aiofiles
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

WEB_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_DIR.parent.resolve()
# 代码与私有数据默认放在同一项目目录；测试/部署可只重定向数据根，
# 避免复制 bin/web 代码，更不会碰真实 meetings/recordings。
DATA_ROOT = Path(os.environ.get(
    "MEETING_DATA_ROOT",
    os.environ.get("MEETING_MINUTES_ROOT", PROJECT_ROOT),  # 兼容旧变量
)).resolve()
ROOT = PROJECT_ROOT  # 保留现有代码路径调用的名字
BANK_DIR = Path(os.environ.get("MEETING_WEB_BANK", DATA_ROOT / "speaker_bank")).resolve()
MEETINGS = DATA_ROOT / "meetings"
INBOX = DATA_ROOT / "recordings" / "inbox"
ORG_FILES = BANK_DIR / "orgchart_files"
JOBS_DIR = Path(os.environ.get("MEETING_WEB_JOBS", WEB_DIR / "jobs")).resolve()
EVALUATIONS_DIR = DATA_ROOT / "evaluations"
STATIC = WEB_DIR / "static"
# 不要 resolve 虚拟环境的 python 符号链接；解析后会退化成 /usr/bin/python，
# 导致后台管线看不到 venv 中的 pyannote/torch 等依赖。
PY = Path(os.environ.get("MEETING_PYTHON", sys.executable))
DRY_RUN = os.environ.get("MEETING_WEB_DRYRUN") == "1"
DRY_RUN_DELAY = float(os.environ.get("MEETING_WEB_DRYRUN_DELAY", "0") or 0)

sys.path.insert(0, str(ROOT / "bin"))
import voice_bank as vb  # noqa: E402
import meeting_dir as md_util  # noqa: E402
import assistant_service as assistant  # noqa: E402
import meeting_artifact as artifact  # noqa: E402
import meeting_structure  # noqa: E402
import export_meeting as meeting_export  # noqa: E402
import evaluation_service as evaluation  # noqa: E402
import translation_service as translation  # noqa: E402

from markdown_it import MarkdownIt  # noqa: E402

MD = MarkdownIt("default", {"html": False})

BANK_LOCK = threading.Lock()      # bank.json / orgchart.json 写操作串行化
EVALUATION_LOCK = threading.Lock()  # 本地人工验收事件串行化
EXEC = ThreadPoolExecutor(max_workers=1)  # 管线/重生成作业单 worker 串行（GPU 资源互斥）
JOBS: dict[str, dict] = {}
PROCS: dict[str, subprocess.Popen] = {}   # 运行中作业的子进程(取消用, 不序列化)

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".wma", ".aiff"}
VTT_EXT = {".vtt"}
ORG_FILE_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}

app = FastAPI(title="meeting-minutes web", docs_url=None, redoc_url=None)


# ---------------------------------------------------------------- 工具

@app.get("/api/health")
def health():
    """不读取会议正文的轻量健康信息，供 UI、doctor 与自动化检查使用。"""
    active = sum(1 for j in JOBS.values() if j.get("status") in ("queued", "running"))
    return {
        "ok": True,
        "dry_run": DRY_RUN,
        "data_root_ready": DATA_ROOT.is_dir(),
        "meetings_ready": MEETINGS.is_dir(),
        "python_ready": PY.is_file(),
        "active_jobs": active,
        "assistant": {"model": assistant.LLM_MODEL, "local_only": not assistant.ALLOW_REMOTE,
                      "rag": assistant.rag_service.RAG_VERSION,
                      "retrieval_models": assistant.rag_service.retrieval_models.status()},
    }

def _now() -> float:
    return time.time()


def _safe(text: str) -> str:
    """与 bin/voice_tool.py 的试听片段文件名规则一致。"""
    return "".join(c if c.isalnum() or c in "-_()（）" else "_" for c in text)


def _mmss(sec: float) -> str:
    s = int(sec)
    return f"{s // 60:02d}:{s % 60:02d}"


def _hms(sec: float) -> str:
    s = int(sec)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _parse_ts(ts: str) -> float:
    parts = [int(p) for p in ts.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def _mdir(slug: str) -> Path:
    """会议目录解析 + 防路径穿越。"""
    p = (MEETINGS / slug).resolve()
    if p.parent != MEETINGS.resolve() or not p.is_dir():
        raise HTTPException(404, "会议不存在")
    return p


def _source(mdir: Path) -> dict:
    sp = mdir / "source.json"
    if sp.is_file():
        try:
            return json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _source_path(mdir: Path, *keys: str) -> Path | None:
    source = _source(mdir)
    for key in keys:
        raw = source.get(key)
        if not raw:
            continue
        path = Path(str(raw))
        path = path if path.is_absolute() else mdir / path
        if path.is_file():
            return path.resolve()
    return None


def _audio_path(mdir: Path) -> Path | None:
    local = mdir / "audio.wav"
    if local.is_file():
        return local
    candidates = sorted(mdir.glob("source_audio.*"))
    return next((p for p in candidates if p.is_file()), None) or _source_path(
        mdir, "audio", "wav", "original_audio")


def _video_path(mdir: Path) -> Path | None:
    candidates = sorted(mdir.glob("source_video.*"))
    return next((p for p in candidates if p.is_file()), None) or _source_path(
        mdir, "mp4", "video", "original_mp4")


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _minutes_file(mdir: Path) -> Path | None:
    for name in ("minutes.md", "minutes.spk.md"):
        p = mdir / name
        if p.is_file():
            return p
    return None


def _current_evidence(mdir: Path) -> dict:
    """只返回与当前逐字稿/纪要 revision 一致的证据，避免展示过期链接。"""
    evidence = _read_json(mdir / "minutes.evidence.json", {})
    minutes = _minutes_file(mdir)
    if not evidence or minutes is None:
        return {}
    revisions = evidence.get("revisions", {})
    if revisions.get("transcript") != assistant.revision(mdir / "transcript.spk.json"):
        return {}
    if revisions.get("minutes") != assistant.revision(minutes):
        return {}
    return evidence


def _evidence_state(mdir: Path, evidence: dict | None = None) -> str:
    """把 sidecar/revision 细节收敛成用户可理解的三态。"""
    current = _current_evidence(mdir) if evidence is None else evidence
    if current:
        return "ready" if current.get("claims") else "partial"
    return "stale" if (mdir / "minutes.evidence.json").is_file() else "partial"


def _refresh_evidence(mdir: Path) -> dict:
    """在确定性编辑后重建 sidecar；不调用 LLM。"""
    minutes_path = _minutes_file(mdir)
    if minutes_path is None or not (mdir / "transcript.spk.json").is_file():
        return {}
    turns = _read_json(mdir / "transcript.spk.json", [])
    pages = [p for p in _read_json(mdir / "slides.json", [])
             if p.get("kind", "slide") == "slide" and p.get("page") is not None]
    raw_desc = _read_json(mdir / "page_desc.json", {}).get("desc", {})
    descs = {int(k): str(v) for k, v in raw_desc.items() if str(k).isdigit()}
    profiles = artifact.load_speaker_profiles(turns, BANK_DIR)
    previous = _read_json(mdir / "minutes.evidence.json", {}).get("generation", {})
    _path, evidence = artifact.write_evidence_document(
        mdir, minutes_path.read_text(encoding="utf-8"), turns, pages, descs, profiles,
        generation={**previous, "refreshed_after_edit": True})
    return evidence


def _slugify(name: str) -> str:
    """与 bin/teams_minutes.py 的 slugify 一致（用于预测会议目录名）。"""
    name = re.sub(r"-?\d{8}(_\d{6})?", "", name)
    name = re.sub(r"-?Meeting[_ ]Recording", "", name, flags=re.I)  # 兼容 _safe() 的下划线名
    name = re.sub(r"[^\w一-鿿-]+", "-", name).strip("-")
    return re.sub(r"-{2,}", "-", name) or "meeting"


def _meeting_identity(slug: str) -> dict:
    """把目录 slug 转为面向用户的标题与日期；不读取会议正文。"""
    match = re.match(r"^(\d{4}-\d{2}-\d{2})_(.+)$", slug)
    date, raw = (match.group(1), match.group(2)) if match else ("", slug)
    if re.fullmatch(r"\d{6}", raw):
        title = f"录音 {raw[:2]}:{raw[2:4]}"
    else:
        title = re.sub(r"[_-]+", " ", raw).strip()
        title = re.sub(r"\s+", " ", title)
    return {"title": title or "未命名会议", "date": date}


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


def _new_job(kind: str, **kw) -> dict:
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "kind": kind, "status": "queued", "created": _now(),
           "started": None, "finished": None, "rc": None, "log": [], **kw}
    with BANK_LOCK:
        JOBS[jid] = job
        _save_job(job)
    return job


def _load_jobs():
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
        (("asr", "transcrib", "转写", "字幕"), "语音转写"),
        (("diar", "speaker", "发言人", "分离"), "区分发言人"),
        (("slide", "extract", "抽页", "抽屏幕", "逻辑页", "幻灯片"), "提取共享画面"),
        (("vl", "vision", "画面理解", "页面理解"), "理解共享画面"),
        (("minute", "summary", "纪要", "总结"), "生成纪要"),
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
        _set_status(job, "done" if proc.returncode == 0 else "failed",
                    finished=_now(), rc=proc.returncode,
                    result={"dry_run": True} if DRY_RUN and proc.returncode == 0 else None)


# ---------------------------------------------------------------- 会议与媒体

@app.get("/api/meetings")
def list_meetings():
    out = []
    if MEETINGS.is_dir():
        for d in sorted(MEETINGS.iterdir(), key=lambda p: p.name, reverse=True):
            if not d.is_dir():
                continue
            item = {"slug": d.name, "has_transcript": False, "has_minutes": False,
                    "has_video": False, "turns": 0, "pages": 0, "duration": None,
                    "speaker_count": 0, **_meeting_identity(d.name)}
            turns = _read_json(d / "transcript.spk.json", [])
            if turns:
                item["has_transcript"] = True
                item["turns"] = len(turns)
                item["duration"] = max((t.get("end", 0) for t in turns), default=0)
                item["speaker_count"] = len({t.get("speaker") for t in turns if t.get("speaker")})
            slides = _read_json(d / "slides.json", [])
            item["pages"] = sum(1 for p in slides if p.get("kind") == "slide") or len(slides)
            item["has_minutes"] = _minutes_file(d) is not None
            item["has_video"] = _video_path(d) is not None
            out.append(item)
    return {"meetings": out}


TOPIC_RE = re.compile(r"^#{2,4}\s*(?:第(\d+)页\s*)?\[(\d{1,3}:\d{2}(?::\d{2})?)\]\s*(.*)$", re.M)


def _minutes_html(mdir: Path, slug: str):
    mf = _minutes_file(mdir)
    if mf is None:
        return "", []
    full_text = artifact.normalize_minutes_markdown(mf.read_text(encoding="utf-8"))
    # 章节定位仍可读取 canonical 逐页标题；常规纪要阅读层不重复铺开逐页详情。
    topics = [{"page": int(m.group(1)) if m.group(1) else None,
               "start": _parse_ts(m.group(2)),
               "title": m.group(3).strip()}
              for m in TOPIC_RE.finditer(full_text)]
    reading_text = artifact.minutes_reading_markdown(full_text)
    reading_text = artifact.markdown_with_evidence_links(
        reading_text, _current_evidence(mdir))
    html = MD.render(reading_text)
    # 纪要里的 slides/ 相对图片 → 本服务 file 路由
    html = html.replace('src="slides/', f'src="/api/meetings/{slug}/file?path=slides/')
    return html, topics


@app.post("/api/meetings/{slug}/delete")
def delete_meeting(slug: str):
    """删除整个会议目录, 并清掉声纹库 sources 里对它的引用。"""
    mdir = _mdir(slug)
    shutil.rmtree(mdir)
    evaluation_removed = False
    evaluation_path = EVALUATIONS_DIR / f"{slug}.json"
    if evaluation_path.is_file():
        evaluation_path.unlink()
        evaluation_removed = True
    removed = 0
    with BANK_LOCK:
        bank = vb.load_bank(BANK_DIR)
        for v in bank["voices"]:
            srcs = v.get("sources", [])
            if slug in srcs:
                srcs.remove(slug)
                removed += 1
        if removed:
            vb.save_bank(BANK_DIR, bank)
    return {"ok": True, "bank_refs_removed": removed,
            "evaluation_removed": evaluation_removed}


@app.get("/api/meetings/{slug}/bundle")
def get_bundle(slug: str):
    mdir = _mdir(slug)
    transcript = _read_json(mdir / "transcript.spk.json", [])
    slides = _read_json(mdir / "slides.json", [])
    minutes_html, topics = _minutes_html(mdir, slug)
    src = _source(mdir)
    samples_dir = mdir / "samples"
    samples = sorted(p.stem for p in samples_dir.glob("*.wav")) if samples_dir.is_dir() else []
    evidence = _current_evidence(mdir)
    duration = max((turn.get("end", 0) for turn in transcript), default=0)
    raw_desc = _read_json(mdir / "page_desc.json", {}).get("desc", {})
    descriptions = {int(key): str(value) for key, value in raw_desc.items()
                    if str(key).isdigit()}
    minutes_path = _minutes_file(mdir)
    structure = meeting_structure.build_structure(
        minutes_path.read_text(encoding="utf-8") if minutes_path else "",
        transcript, slides, descriptions, evidence, duration=duration)
    # VL 结果本身通常是 Markdown；沿用纪要的安全渲染配置（禁用原始 HTML），
    # 让屏幕内容页保持可读层级，而不是把标题/列表作为原始文本展示。
    for visual in structure.get("visuals", []):
        visual["description_html"] = MD.render(
            visual.get("display_description") or "当前画面没有可用的 VL 详细解读。")
    return {
        "slug": slug,
        **_meeting_identity(slug),
        "transcript": transcript,
        "slides": slides,
        "minutes_html": minutes_html,
        "has_minutes": bool(minutes_html),
        "topics": topics,
        "samples": samples,
        "source": {k: bool(v) for k, v in src.items()},  # 不把原始路径暴露给前端逻辑判断以外
        "has_audio": _audio_path(mdir) is not None,
        "has_video": _video_path(mdir) is not None,
        "duration": duration,
        "speaker_count": len({t.get("speaker") for t in transcript if t.get("speaker")}),
        "transcript_revision": assistant.revision(mdir / "transcript.spk.json"),
        "minutes_revision": assistant.revision(_minutes_file(mdir)) if _minutes_file(mdir) else None,
        "document_state": "ready" if transcript and minutes_html else "processing",
        "structure": structure,
        "evidence": {
            "schema": evidence.get("schema"),
            "state": _evidence_state(mdir, evidence),
            "claims": evidence.get("claims", []),
            "actions": evidence.get("actions") or artifact.action_items_from_claims(
                evidence.get("claims", [])),
            "linkage": evidence.get("linkage", {}),
        },
    }


# ---------------------------------------------------------------- 纪要质量验收

class QualityReviewReq(BaseModel):
    label: str
    note: str = Field(default="", max_length=1000)
    claim_fingerprint: str


def _evaluation_path(slug: str) -> Path:
    # slug 已由 _mdir 校验为 MEETINGS 的直接子目录名。
    return EVALUATIONS_DIR / f"{slug}.json"


def _quality_payload(slug: str, mdir: Path) -> dict:
    evidence = _current_evidence(mdir)
    if evidence:
        evidence_state = "ready"
    elif (mdir / "minutes.evidence.json").is_file():
        evidence_state = "stale"
    else:
        evidence_state = "missing"
    store = evaluation.load_store(_evaluation_path(slug), slug)
    return evaluation.build_payload(slug, evidence, store, evidence_state)


@app.get("/api/meetings/{slug}/quality")
def get_quality_review(slug: str):
    """返回当前结论与本机人工验收；不运行模型，也不修改正式纪要。"""
    mdir = _mdir(slug)
    return _quality_payload(slug, mdir)


@app.put("/api/meetings/{slug}/quality/claims/{claim_id}")
def put_quality_review(slug: str, claim_id: str, req: QualityReviewReq):
    mdir = _mdir(slug)
    evidence = _current_evidence(mdir)
    if not evidence:
        raise HTTPException(409, "纪要依据缺失或已过期，请先重新生成纪要")
    claim = next((item for item in evidence.get("claims", []) if item.get("id") == claim_id), None)
    if claim is None:
        raise HTTPException(404, "结论不存在")
    current_fingerprint = evaluation.claim_fingerprint(claim, evidence)
    if req.claim_fingerprint != current_fingerprint:
        raise HTTPException(409, "结论或依据已变化，请刷新后重新判断")
    try:
        with EVALUATION_LOCK:
            evaluation.save_review(
                _evaluation_path(slug), slug, evidence, claim, req.label, req.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _quality_payload(slug, mdir)


# ---------------------------------------------------------------- 逐字稿翻译

def _translation_payload(slug: str, mdir: Path, target: str) -> dict:
    ident = _meeting_identity(slug)
    return translation.translation_payload(
        mdir, ident["title"], _current_evidence(mdir), target=target)


def _run_translation(job: dict, mdir: Path, title: str, target: str) -> None:
    """同一串行 worker 内执行本地翻译；作业日志只记录进度数字。"""
    if job.get("cancel_requested"):
        return
    target_label = translation.TARGETS[target]["label"]
    _set_status(job, "running", started=_now(), stage=f"生成{target_label}译文",
                progress={"done": 0, "total": 0})

    def cancelled() -> bool:
        return bool(job.get("cancel_requested"))

    def progress(done: int, total: int) -> None:
        if cancelled():
            return
        with BANK_LOCK:
            job["progress"] = {"done": done, "total": total}
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
            job.setdefault("log", []).append(f"[error] 翻译失败 ({type(exc).__name__})")
            _set_status(job, "failed", finished=_now(), rc=None)
        return
    if cancelled():
        if job.get("status") != "cancelled":
            _set_status(job, "cancelled", finished=_now(), rc=None)
        return
    _set_status(
        job, "done", finished=_now(), rc=0,
        result={"target_language": target, "translated": len(document.get("turns", [])),
                "total": document.get("total", 0), "dry_run": DRY_RUN})


@app.get("/api/meetings/{slug}/translations/transcript")
def get_transcript_translation(
        slug: str, target: str = Query("zh-CN", pattern="^(zh-CN|en)$")):
    mdir = _mdir(slug)
    return _translation_payload(slug, mdir, target)


@app.post("/api/meetings/{slug}/translations/transcript")
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
    existing = next((job for job in JOBS.values()
                     if job.get("kind") == "translation" and job.get("meeting") == slug
                     and job.get("target_language") == target
                     and job.get("status") in {"queued", "running"}), None)
    if existing:
        if focus_indexes:
            with BANK_LOCK:
                combined = existing.get("focus_turn_indexes", []) + focus_indexes
                existing["focus_turn_indexes"] = list(dict.fromkeys(combined))[-30:]
                _save_job(existing)
        return dict(existing)
    job = _new_job("translation", meeting=slug, target_language=target,
                   focus_turn_indexes=focus_indexes,
                   progress={"done": len(current.get("turns", [])), "total": total_turns})
    response = dict(job)
    EXEC.submit(_run_translation, job, mdir, _meeting_identity(slug)["title"], target)
    return response


@app.get("/api/meetings/{slug}/export")
def export_meeting_pack(slug: str, media: str = Query("none", pattern="^(none|audio|video)$")):
    """生成静态 MeetingPack；默认不带媒体，收件人无需本机模型或 Web 服务。"""
    mdir = _mdir(slug)
    fd, temp_name = tempfile.mkstemp(prefix="meetingpack-", suffix=".zip")
    os.close(fd)
    archive = Path(temp_name)
    ident = _meeting_identity(slug)
    try:
        meeting_export.export_meeting(
            mdir, archive, bank_dir=BANK_DIR, media_mode=media,
            title=ident["title"], date=ident["date"])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        archive.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc
    filename = f"{_safe(ident['title']) or 'meeting'}.meetingpack.zip"
    return FileResponse(
        archive, media_type="application/zip", filename=filename,
        background=BackgroundTask(archive.unlink, missing_ok=True))


@app.get("/api/meetings/{slug}/export/preflight")
def export_meeting_preflight(slug: str):
    """返回导出前所需的数量与体积元数据；不复制会议正文或本机路径。"""
    mdir = _mdir(slug)
    ident = _meeting_identity(slug)
    transcript = _read_json(mdir / "transcript.spk.json", [])
    slides = _read_json(mdir / "slides.json", [])
    evidence = _current_evidence(mdir)
    claims = evidence.get("claims", [])
    linked_claims = sum(bool(claim.get("turn_ids") or claim.get("turn_indexes")
                             or claim.get("page_ids")) for claim in claims)
    base_paths = [
        mdir / "transcript.spk.json",
        mdir / "transcript.spk.md",
        mdir / "minutes.evidence.json",
        _minutes_file(mdir),
    ]
    base_bytes = 180_000  # viewer、manifest、README 与导出索引的保守开销
    for path in base_paths:
        if path and path.is_file():
            base_bytes += path.stat().st_size
    slides_dir = mdir / "slides"
    if slides_dir.is_dir():
        base_bytes += sum(path.stat().st_size for path in slides_dir.iterdir() if path.is_file())
    audio = _audio_path(mdir)
    video = _video_path(mdir)
    audio_bytes = audio.stat().st_size if audio else 0
    video_bytes = video.stat().st_size if video else 0
    return {
        **ident,
        "document_state": "ready" if transcript and _minutes_file(mdir) else "processing",
        "evidence": {
            "state": _evidence_state(mdir, evidence),
            "claims": len(claims),
            "linked_claims": linked_claims,
            "linkage_coverage": round(linked_claims / len(claims), 3) if claims else 0,
        },
        "content": {
            "transcript_turns": len(transcript),
            "pages": sum(1 for page in slides if page.get("kind") == "slide") or len(slides),
        },
        "media": {
            "audio": {"available": bool(audio), "bytes": audio_bytes},
            "video": {"available": bool(video), "bytes": video_bytes},
        },
        "estimated_bytes": {
            "none": base_bytes,
            "audio": base_bytes + audio_bytes,
            "video": base_bytes + video_bytes,
        },
    }


# ---------------------------------------------------------------- 本地会议助手

class AssistantChatReq(BaseModel):
    message: str
    turn_indexes: list[int] = Field(default_factory=list)
    transcript_revision: str | None = None
    history: list[dict] = Field(default_factory=list)


class AssistantEditReq(BaseModel):
    message: str
    turn_indexes: list[int] = Field(default_factory=list)
    transcript_revision: str | None = None
    minutes_revision: str | None = None
    target_heading: str | None = None


class AssistantApplyReq(BaseModel):
    proposal_id: str


class RagSearchReq(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    turn_indexes: list[int] = Field(default_factory=list, max_length=30)


def _assistant_message(text: str) -> str:
    value = text.strip()
    if not value:
        raise HTTPException(400, "请输入问题或修改要求")
    if len(value) > 8000:
        raise HTTPException(400, "单次输入不能超过 8000 个字符")
    return value


def _assistant_http_error(exc: assistant.AssistantError):
    raise HTTPException(exc.status, str(exc)) from exc


@app.post("/api/meetings/{slug}/assistant/chat")
def assistant_chat(slug: str, req: AssistantChatReq):
    mdir = _mdir(slug)
    transcript = mdir / "transcript.spk.json"
    if not transcript.is_file():
        raise HTTPException(400, "没有逐字稿，无法进行会议问答")
    try:
        return assistant.answer_question(
            mdir, _assistant_message(req.message), req.turn_indexes,
            req.transcript_revision, req.history, DRY_RUN)
    except assistant.AssistantError as exc:
        _assistant_http_error(exc)


@app.post("/api/meetings/{slug}/rag/search")
def rag_search(slug: str, req: RagSearchReq):
    """只运行检索、不调用 LLM；用于检查召回来源和后续轻量 Viewer 接入。"""
    mdir = _mdir(slug)
    if not (mdir / "transcript.spk.json").is_file():
        raise HTTPException(400, "没有逐字稿，无法检索")
    try:
        result = assistant.rag_service.retrieve(mdir, req.query.strip(), req.turn_indexes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    result.pop("context", None)
    return result


@app.post("/api/meetings/{slug}/assistant/edit/preview")
def assistant_edit_preview(slug: str, req: AssistantEditReq):
    mdir = _mdir(slug)
    transcript = mdir / "transcript.spk.json"
    minutes = _minutes_file(mdir)
    if not transcript.is_file() or minutes is None:
        raise HTTPException(400, "需要逐字稿和纪要才能生成修改预览")
    try:
        return assistant.preview_minutes_edit(
            minutes, transcript, _assistant_message(req.message), req.turn_indexes,
            req.transcript_revision, req.minutes_revision, req.target_heading, DRY_RUN)
    except assistant.AssistantError as exc:
        _assistant_http_error(exc)


@app.post("/api/meetings/{slug}/assistant/edit/apply")
def assistant_edit_apply(slug: str, req: AssistantApplyReq):
    mdir = _mdir(slug)
    minutes = _minutes_file(mdir)
    if minutes is None:
        raise HTTPException(400, "没有可修改的纪要")
    try:
        result = assistant.apply_minutes_edit(minutes, req.proposal_id)
        _refresh_evidence(mdir)
        return result
    except assistant.AssistantError as exc:
        _assistant_http_error(exc)


@app.post("/api/meetings/{slug}/assistant/edit/undo")
def assistant_edit_undo(slug: str, req: AssistantApplyReq):
    mdir = _mdir(slug)
    minutes = _minutes_file(mdir)
    if minutes is None:
        raise HTTPException(400, "没有可恢复的纪要")
    try:
        result = assistant.undo_minutes_edit(minutes, req.proposal_id)
        _refresh_evidence(mdir)
        return result
    except assistant.AssistantError as exc:
        _assistant_http_error(exc)


@app.get("/api/meetings/{slug}/media/audio")
def media_audio(slug: str):
    p = _audio_path(_mdir(slug))
    if p is None:
        raise HTTPException(404, "没有音频")
    media_type = mimetypes.guess_type(p.name)[0] or "audio/wav"
    return FileResponse(p, media_type=media_type)


@app.get("/api/meetings/{slug}/media/video")
def media_video(slug: str):
    p = _video_path(_mdir(slug))
    if p is None:
        raise HTTPException(404, "没有源视频")
    media_type = mimetypes.guess_type(p.name)[0] or "video/mp4"
    return FileResponse(p, media_type=media_type)


@app.get("/api/meetings/{slug}/file")
def meeting_file(slug: str, path: str = Query(...)):
    mdir = _mdir(slug)
    p = (mdir / path).resolve()
    if not p.is_file() or not p.is_relative_to(mdir):
        raise HTTPException(404, "文件不存在")
    return FileResponse(p)


@app.get("/api/meetings/{slug}/samples/{filename}")
def sample_file(slug: str, filename: str):
    if not filename.endswith(".wav"):
        raise HTTPException(404, "只提供 wav 试听")
    name = filename[:-4]
    mdir = _mdir(slug)
    if re.fullmatch(r"v_\d+", name):  # 允许按声纹 id 取（映射到显示名）
        bank = vb.load_bank(BANK_DIR)
        v = next((v for v in bank["voices"] if v["id"] == name), None)
        if v:
            name = vb.display_name(bank, v)
    p = mdir / "samples" / f"{_safe(name)}.wav"
    if not p.is_file():
        raise HTTPException(404, "没有试听片段")
    return FileResponse(p, media_type="audio/wav")


# ---------------------------------------------------------------- 说话人 / 声纹库

def _resolve_or_409(bank: dict, name: str, orgchart=None):
    """返回 (person, how)；未命中时抛 409(候选 + can_create 提示前端可新建)。"""
    person, how = vb.resolve_person(bank, name, orgchart=orgchart)
    if person is None:
        cands = [{"id": p.get("id"),
                  "name": p.get("display_name") or p.get("name", ""),
                  "names": p.get("names", []), "aliases": p.get("aliases", []),
                  "score": p.get("_match_score")}
                 for p in (how or [])]
        raise HTTPException(409, {"ok": False, "candidates": cands, "can_create": True,
                                  "detail": "没有精确命中：可从候选选择，或用 create=true 新建此人"})
    return person, how


def _bind_voice(voice_id: str, name: str, create: bool = False):
    """声纹 → 人。create=true 时库内精确名没有就直接新建 person。返回 (显示名, how)。"""
    with BANK_LOCK:
        bank = vb.load_bank(BANK_DIR)
        voice = next((v for v in bank["voices"] if v["id"] == voice_id), None)
        if not voice:
            raise HTTPException(404, "没有这条声纹")
        if create:
            person, how = vb.resolve_person(bank, name)
            if person is None:
                person = vb.add_person(bank, name.strip(), display_name=name.strip())
                how = "新建"
        else:
            org = vb.load_orgchart(BANK_DIR)
            person, how = _resolve_or_409(bank, name, orgchart=org)
        voice["person_id"] = person["id"]
        vb.save_bank(BANK_DIR, bank)
        return vb.person_name(bank, person["id"]), (how if isinstance(how, str) else "新建")


TURN_LINE_RE = re.compile(r"^\[\d{1,3}:\d{2}(?::\d{2})?\] \*\*")


def _rewrite_spk_md(mdir: Path, slug: str, turns: list):
    """按 json 重建 transcript.spk.md 正文；保留原文件头，沿用原时间格式(mm:ss / hh:mm:ss)。"""
    mp = mdir / "transcript.spk.md"
    fmt = _mmss
    head = f"# {slug} 逐字稿(具名)\n\n"
    if mp.is_file():
        lines = mp.read_text(encoding="utf-8").splitlines(keepends=True)
        i = next((k for k, l in enumerate(lines) if TURN_LINE_RE.match(l)), len(lines))
        if i < len(lines):
            head = "".join(lines[:i])
            if re.match(r"^\[\d{1,3}:\d{2}:\d{2}\]", lines[i]):
                fmt = _hms
    body = "\n\n".join(f"[{fmt(t['start'])}] **{t['speaker']}**: {t['text']}"
                       for t in turns) + "\n"
    mp.write_text(head + body, encoding="utf-8")


def _rename_voice_in_meeting(mdir: Path, slug: str, voice_id: str, new_name: str) -> int:
    tp = mdir / "transcript.spk.json"
    turns = _read_json(tp, [])
    old_names, n = set(), 0
    for t in turns:
        if t.get("voice") == voice_id:
            old_names.add(t.get("speaker", ""))
            t["speaker"] = new_name
            n += 1
    if n == 0:
        return 0
    tp.write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")
    _rewrite_spk_md(mdir, slug, turns)
    # 试听片段跟随改名（best-effort）
    samples = mdir / "samples"
    for old in old_names:
        src, dst = samples / f"{_safe(old)}.wav", samples / f"{_safe(new_name)}.wav"
        if src.is_file() and not dst.exists():
            src.rename(dst)
    return n


class BindReq(BaseModel):
    voice: str
    name: str
    create: bool = False


@app.post("/api/meetings/{slug}/bind")
def bind_in_meeting(slug: str, req: BindReq):
    """一次交互绑定该 voice 在本会议的全部语句。"""
    mdir = _mdir(slug)
    new_name, how = _bind_voice(req.voice, req.name, req.create)
    n = _rename_voice_in_meeting(mdir, slug, req.voice, new_name)
    if n:
        _refresh_evidence(mdir)
    return {"ok": True, "name": new_name, "turns": n, "how": how}


@app.get("/api/speakers")
def list_speakers():
    bank = vb.load_bank(BANK_DIR)
    voices = [{"id": v["id"], "person_id": v.get("person_id"),
               "name": vb.display_name(bank, v),
               "label_hint": v.get("label_hint", ""),
               "sources": v.get("sources", []),
               "created": v.get("created", "")}
              for v in bank["voices"]]
    persons = [{"id": p["id"], "name": p["name"],
                "display_name": p.get("display_name") or p["name"],
                "names": p.get("names", []), "aliases": p.get("aliases", []),
                "created": p.get("created", ""),
                "voices": sum(1 for v in bank["voices"] if v.get("person_id") == p["id"])}
               for p in bank["persons"]]
    return {"persons": persons, "voices": voices}


def _voice_sample(voice_id: str) -> Path | None:
    """从声纹来源会议中找一个代表试听片段；不在 API 中暴露磁盘路径。"""
    bank = vb.load_bank(BANK_DIR)
    voice = next((v for v in bank["voices"] if v["id"] == voice_id), None)
    if voice is None:
        raise HTTPException(404, "没有这条声纹")
    candidates = [vb.display_name(bank, voice), voice.get("label_hint", ""), voice_id]
    for slug in reversed(voice.get("sources", [])):
        mdir = (MEETINGS / slug).resolve()
        if mdir.parent != MEETINGS.resolve() or not mdir.is_dir():
            continue
        for turn in _read_json(mdir / "transcript.spk.json", []):
            if turn.get("voice") == voice_id:
                candidates.insert(0, turn.get("speaker", ""))
                break
        for value in candidates:
            p = mdir / "samples" / f"{_safe(value)}.wav"
            if value and p.is_file():
                return p
    return None


@app.get("/api/speakers/{voice_id}/sample")
def speaker_sample(voice_id: str):
    p = _voice_sample(voice_id)
    if p is None:
        raise HTTPException(404, "没有可用试听片段")
    return FileResponse(p, media_type="audio/wav")


class PersonPutReq(BaseModel):
    display_name: str
    names: list[dict] = Field(default_factory=list)


@app.put("/api/speakers/person/{person_id}")
def update_person(person_id: str, req: PersonPutReq):
    display = req.display_name.strip()
    if not display:
        raise HTTPException(400, "首选显示名不能为空")
    typed = []
    for item in req.names:
        value = str(item.get("value", "")).strip()
        if not value:
            continue
        kind = str(item.get("type", "other"))
        typed.append({"value": value,
                      "type": kind if kind in vb.NAME_TYPES else "other",
                      "verified": bool(item.get("verified", True))})
    if not any(vb.normalize_name(n["value"]) == vb.normalize_name(display) for n in typed):
        typed.append({"value": display, "type": "other", "verified": True})
    with BANK_LOCK:
        bank = vb.load_bank(BANK_DIR)
        person = next((p for p in bank["persons"] if p["id"] == person_id), None)
        if person is None:
            raise HTTPException(404, "没有这个人")
        person["display_name"] = display
        person["names"] = typed
        vb.normalize_person(person)
        linked_voices = [v for v in bank["voices"] if v.get("person_id") == person_id]
        vb.save_bank(BANK_DIR, bank)
    changed_turns, changed_meeting_ids = 0, set()
    for voice in linked_voices:
        for slug in voice.get("sources", []):
            mdir = (MEETINGS / slug).resolve()
            if mdir.parent != MEETINGS.resolve() or not mdir.is_dir():
                continue
            count = _rename_voice_in_meeting(mdir, slug, voice["id"], display)
            changed_turns += count
            if count:
                changed_meeting_ids.add(slug)
    for slug in changed_meeting_ids:
        _refresh_evidence(MEETINGS / slug)
    return {"ok": True, "id": person_id, "display_name": person["display_name"],
            "names": person["names"], "meetings": len(changed_meeting_ids),
            "turns": changed_turns}


@app.post("/api/speakers/bind")
def bind_voice_only(req: BindReq):
    """只在声纹库层面绑定（不改任何会议）。"""
    new_name, how = _bind_voice(req.voice, req.name, req.create)
    return {"ok": True, "name": new_name, "how": how}


class AliasReq(BaseModel):
    person: str
    aliases: list[str]


@app.post("/api/speakers/alias")
def add_alias(req: AliasReq):
    with BANK_LOCK:
        bank = vb.load_bank(BANK_DIR)
        person, _how = vb.resolve_person(bank, req.person)  # 与 voice_tool alias 一致：不带 orgchart
        if person is None:
            raise HTTPException(404, "没找到这个人")
        for a in req.aliases:
            if a and a not in person["aliases"]:
                person["aliases"].append(a)
        vb.save_bank(BANK_DIR, bank)
        return {"ok": True, "name": vb.person_name(bank, person["id"]),
                "aliases": person["aliases"]}


class MergeReq(BaseModel):
    keep: str
    drop: list[str]


@app.post("/api/speakers/merge")
def merge_voices(req: MergeReq):
    with BANK_LOCK:
        bank = vb.load_bank(BANK_DIR)
        keep = next((v for v in bank["voices"] if v["id"] == req.keep), None)
        if not keep:
            raise HTTPException(404, f"没有这条声纹: {req.keep}")
        if not keep.get("person_id"):
            p = vb.add_person(bank, keep.get("label_hint") or keep["id"])
            keep["person_id"] = p["id"]
        merged = 0
        for did in req.drop:
            drop = next((v for v in bank["voices"] if v["id"] == did), None)
            if not drop or did == req.keep:
                continue
            drop["person_id"] = keep["person_id"]
            for s in drop.get("sources", []):
                if s not in keep.setdefault("sources", []):
                    keep["sources"].append(s)
            merged += 1
        vb.save_bank(BANK_DIR, bank)
        return {"ok": True, "merged": merged,
                "name": vb.person_name(bank, keep["person_id"])}


class VoiceReq(BaseModel):
    voice: str


@app.post("/api/speakers/unbind")
def unbind_voice(req: VoiceReq):
    with BANK_LOCK:
        bank = vb.load_bank(BANK_DIR)
        voice = next((v for v in bank["voices"] if v["id"] == req.voice), None)
        if not voice:
            raise HTTPException(404, "没有这条声纹")
        voice["person_id"] = None
        vb.save_bank(BANK_DIR, bank)
        return {"ok": True}


# ---------------------------------------------------------------- Org chart

def _org_entry_id(name: str, index: int) -> str:
    return "o_" + uuid.uuid5(uuid.NAMESPACE_URL, f"meeting-org:{index}:{name}").hex[:12]


def _normalize_org_entries(raw_entries: list[dict]) -> list[dict]:
    """兼容 leader=姓名的旧数据，并为图编辑器补稳定节点/上级 ID。"""
    entries, used = [], set()
    for index, raw in enumerate(raw_entries):
        name = str(raw.get("name", "")).strip()
        node_id = str(raw.get("id", "")).strip() or _org_entry_id(name, index)
        if node_id in used:
            node_id = _org_entry_id(name, index)
        used.add(node_id)
        entries.append({
            "id": node_id,
            "person_id": str(raw.get("person_id", "")).strip() or None,
            "name": name,
            "aliases": [str(a).strip() for a in raw.get("aliases", []) if str(a).strip()],
            "title": str(raw.get("title", "")).strip(),
            "team": str(raw.get("team", "")).strip(),
            "manager_id": str(raw.get("manager_id", "")).strip() or None,
            "leader": str(raw.get("leader", "")).strip(),
            "leader_raw": str(raw.get("leader_raw", raw.get("leader", ""))).strip(),
            "status": str(raw.get("status", "")).strip(),
            "source_pages": [int(x) for x in raw.get("source_pages", [])
                             if isinstance(x, (int, float, str)) and str(x).isdigit()],
            "conflicts": [str(x) for x in raw.get("conflicts", []) if str(x).strip()],
            "note": str(raw.get("note", "")).strip(),
        })
    by_id = {e["id"]: e for e in entries}
    by_name: dict[str, list[str]] = {}
    for e in entries:
        by_name.setdefault(vb.normalize_name(e["name"]), []).append(e["id"])
        for alias in e["aliases"]:
            by_name.setdefault(vb.normalize_name(alias), []).append(e["id"])
    for e in entries:
        if e["manager_id"] not in by_id:
            e["manager_id"] = None
        if not e["manager_id"] and e["leader"]:
            matches = list(dict.fromkeys(by_name.get(vb.normalize_name(e["leader"]), [])))
            if len(matches) == 1 and matches[0] != e["id"]:
                e["manager_id"] = matches[0]
        if e["manager_id"]:
            e["leader"] = by_id[e["manager_id"]]["name"]
        if not e["status"]:
            e["status"] = "conflict" if e["conflicts"] else (
                "unresolved" if e["leader_raw"] and not e["manager_id"] else "confirmed")
    return entries


@app.get("/api/orgchart")
def get_orgchart():
    entries = _normalize_org_entries(vb.load_orgchart(BANK_DIR))
    bank = vb.load_bank(BANK_DIR)
    valid_person_ids = {p["id"] for p in bank["persons"]}
    placed = {e["person_id"] for e in entries if e.get("person_id") in valid_person_ids}
    # 旧 Org Chart 没有 person_id：只按唯一的已确认名称精确关联，不做任何模糊合并。
    for entry in entries:
        if entry.get("person_id") in valid_person_ids:
            continue
        person, _how = vb.resolve_person(bank, entry["name"])
        if person is not None:
            entry["person_id"] = person["id"]
            placed.add(person["id"])
    unplaced = [{"id": p["id"], "display_name": p.get("display_name") or p["name"],
                 "name": p["name"], "names": p.get("names", [])}
                for p in bank["persons"] if p["id"] not in placed]
    return {"entries": entries, "unplaced_people": unplaced}


class OrgPut(BaseModel):
    entries: list[dict]


@app.put("/api/orgchart")
def put_orgchart(req: OrgPut):
    """保存图关系；服务端验证上级存在、自指和环路。"""
    supplied_ids = [str(e.get("id", "")).strip() for e in req.entries if e.get("id")]
    if len(supplied_ids) != len(set(supplied_ids)):
        raise HTTPException(400, "存在重复节点 ID")
    supplied_id_set = set(supplied_ids)
    for raw in req.entries:
        raw_manager_id = raw.get("manager_id")
        manager_id = str(raw_manager_id).strip() if raw_manager_id else ""
        if manager_id and manager_id not in supplied_id_set:
            name = str(raw.get("name", "")).strip() or "未命名节点"
            raise HTTPException(400, f"{name} 的上级节点不存在")
    entries = _normalize_org_entries(req.entries)
    if any(not e["name"] for e in entries):
        raise HTTPException(400, "存在空名字条目")
    by_id = {e["id"]: e for e in entries}
    for e in entries:
        manager_id = e.get("manager_id")
        if manager_id and manager_id not in by_id:
            raise HTTPException(400, f"{e['name']} 的上级节点不存在")
        if manager_id == e["id"]:
            raise HTTPException(400, f"{e['name']} 不能成为自己的上级")
        seen, cursor = set(), e["id"]
        while cursor:
            if cursor in seen:
                raise HTTPException(400, "组织架构存在循环汇报关系")
            seen.add(cursor)
            cursor = by_id.get(cursor, {}).get("manager_id")
    with BANK_LOCK:
        BANK_DIR.mkdir(parents=True, exist_ok=True)
        (BANK_DIR / "orgchart.json").write_text(
            json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "count": len(entries)}


@app.post("/api/orgchart/files")
async def upload_org_file(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ORG_FILE_EXT:
        raise HTTPException(400, f"不支持的文件类型: {ext}")
    stem = _safe(Path(file.filename).stem) or "file"
    d = ORG_FILES / stem
    d.mkdir(parents=True, exist_ok=True)
    for p in d.glob("page-*.*"):
        p.unlink()
    orig = d / f"original{ext}"
    async with aiofiles.open(orig, "wb") as out:
        while chunk := await file.read(1 << 20):
            await out.write(chunk)
    if ext == ".pdf":
        rc = subprocess.run(["pdftoppm", "-png", "-r", "110", str(orig), str(d / "page")],
                            capture_output=True).returncode
        pages = len(list(d.glob("page-*.png")))
        if rc != 0 or pages == 0:
            raise HTTPException(500, "PDF 渲染失败")
    else:
        orig.replace(d / f"page-1{ext}")
        pages = 1
    return {"ok": True, "name": stem, "pages": pages}


@app.get("/api/orgchart/files")
def list_org_files():
    out = []
    if ORG_FILES.is_dir():
        for d in sorted(ORG_FILES.iterdir(), key=lambda p: p.name):
            if not d.is_dir():
                continue
            orig = next(iter(d.glob("original.*")), None)
            pages = [p for p in d.glob("page-*.*")
                     if re.fullmatch(r"page-\d+\..+", p.name)]
            out.append({"name": d.name, "pages": len(pages),
                        "kind": "pdf" if orig and orig.suffix == ".pdf" else "image"})
    return {"files": out}


@app.get("/api/orgchart/files/{name}/page/{n}")
def org_file_page(name: str, n: int):
    d = (ORG_FILES / _safe(name)).resolve()
    if not d.is_dir() or not d.is_relative_to(ORG_FILES.resolve()):
        raise HTTPException(404, "文件不存在")
    for p in d.glob("page-*.*"):
        m = re.fullmatch(r"page-(\d+)\..+", p.name)
        if m and int(m.group(1)) == n:
            return FileResponse(p)
    raise HTTPException(404, "没有这一页")


class ExtractReq(BaseModel):
    name: str


@app.post("/api/orgchart/extract")
def extract_orgchart(req: ExtractReq):
    """VL 逐页提取参考文件里的人名/层级 → orgchart_draft.json(人工检查后保存)。"""
    d = (ORG_FILES / _safe(req.name)).resolve()
    if not d.is_dir() or not d.is_relative_to(ORG_FILES.resolve()):
        raise HTTPException(404, "没有这个参考文件")
    if not list(d.glob("page-*.png")):
        raise HTTPException(400, "该文件没有渲染页图")
    cmd = [str(PY), str(ROOT / "bin" / "orgchart_extract.py"), _safe(req.name)]
    job = _new_job("orgchart_extract", meeting=req.name, cmd=cmd)
    resp = dict(job)
    EXEC.submit(_run_pipeline, job)
    return resp


@app.get("/api/orgchart/draft")
def orgchart_draft():
    p = BANK_DIR / "orgchart_draft.json"
    if not p.is_file():
        return {"entries": [], "has_draft": False}
    return {"entries": _normalize_org_entries(_read_json(p, [])), "has_draft": True}


# ---------------------------------------------------------------- 上传与作业

def _predict_meeting(route: str, primary: Path, vtt: Path | None) -> str:
    if route == "audio":
        return md_util.for_recording(DATA_ROOT, primary.stem, None).name
    date_m = re.search(r"(\d{8})", primary.name)
    stem = vtt.stem if (route == "teams" and vtt is not None) else primary.stem
    return md_util.for_teams(DATA_ROOT, _slugify(stem),
                             date_m.group(1) if date_m else "").name


@app.post("/api/upload")
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


@app.post("/api/meetings/{slug}/regen_minutes")
def regen_minutes(slug: str, refine: str = Query("")):
    mdir = _mdir(slug)
    if not (mdir / "transcript.spk.json").is_file():
        raise HTTPException(400, "没有逐字稿，无法重生成")
    cmd = [str(PY), str(ROOT / "bin" / "minutes_by_page.py"), str(mdir)]
    if refine:
        cmd += ["--refine-model", refine]
    job = _new_job("regen", meeting=slug, cmd=cmd)
    resp = dict(job)
    EXEC.submit(_run_pipeline, job)
    return resp


@app.get("/api/jobs")
def list_jobs():
    return {"jobs": sorted(JOBS.values(), key=lambda j: j["created"], reverse=True)}


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "没有这条作业")
    return job


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str):
    """取消作业：排队的直接作废；运行中的整进程组 SIGTERM(5s 不死再 SIGKILL)。"""
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "没有这条作业")
    if job["status"] not in ("queued", "running"):
        raise HTTPException(400, f"作业已结束({job['status']})")
    job["cancel_requested"] = True
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


# ---------------------------------------------------------------- 静态页

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/admin")
def admin():
    return FileResponse(STATIC / "admin.html", headers={"Cache-Control": "no-store"})


@app.get("/product")
def product():
    return FileResponse(STATIC / "product.html", headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")

_load_jobs()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("MEETING_WEB_PORT", 8899)),
                log_level="info")
