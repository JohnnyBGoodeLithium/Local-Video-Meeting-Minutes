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
import os
import re
import shutil
import signal
import subprocess
import sys
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
STATIC = WEB_DIR / "static"
PY = Path(os.environ.get("MEETING_PYTHON", PROJECT_ROOT / ".venv" / "bin" / "python")).resolve()
DRY_RUN = os.environ.get("MEETING_WEB_DRYRUN") == "1"
DRY_RUN_DELAY = float(os.environ.get("MEETING_WEB_DRYRUN_DELAY", "0") or 0)

sys.path.insert(0, str(ROOT / "bin"))
import voice_bank as vb  # noqa: E402
import meeting_dir as md_util  # noqa: E402
import assistant_service as assistant  # noqa: E402

from markdown_it import MarkdownIt  # noqa: E402

MD = MarkdownIt("default", {"html": False})

BANK_LOCK = threading.Lock()      # bank.json / orgchart.json 写操作串行化
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
        "assistant": {"model": assistant.LLM_MODEL, "local_only": not assistant.ALLOW_REMOTE},
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


def _run_pipeline(job: dict):
    """后台线程：subprocess 调 bin/ 管线脚本。stdout 只留元数据行。"""
    if job.get("cancel_requested"):   # 排队期间被取消
        return
    _set_status(job, "running", started=_now())
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
            actual, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env={**os.environ, "HF_HUB_OFFLINE": "1"},
            start_new_session=True)   # 独立进程组: 取消时整组杀(含管线拉起的孙进程)
        PROCS[job["id"]] = proc
        out, err = proc.communicate()
    except Exception as e:
        job["log"].append(f"[error] 启动失败: {type(e).__name__}: {e}")
        _set_status(job, "failed", finished=_now(), rc=-1)
        return
    finally:
        PROCS.pop(job["id"], None)
    meta = [l for l in out.splitlines() if l.lstrip().startswith("[")]
    job["log"].extend(meta)
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
            src = _source(d)
            item["has_video"] = bool(src.get("mp4") and Path(src["mp4"]).is_file())
            out.append(item)
    return {"meetings": out}


TOPIC_RE = re.compile(r"^#{2,4}\s*(?:第(\d+)页\s*)?\[(\d{1,3}:\d{2}(?::\d{2})?)\]\s*(.*)$", re.M)


def _minutes_html(mdir: Path, slug: str):
    mf = _minutes_file(mdir)
    if mf is None:
        return "", []
    text = mf.read_text(encoding="utf-8")
    html = MD.render(text)
    # 纪要里的 slides/ 相对图片 → 本服务 file 路由
    html = html.replace('src="slides/', f'src="/api/meetings/{slug}/file?path=slides/')
    topics = [{"page": int(m.group(1)) if m.group(1) else None,
               "start": _parse_ts(m.group(2)),
               "title": m.group(3).strip()}
              for m in TOPIC_RE.finditer(text)]
    return html, topics


@app.post("/api/meetings/{slug}/delete")
def delete_meeting(slug: str):
    """删除整个会议目录, 并清掉声纹库 sources 里对它的引用。"""
    mdir = _mdir(slug)
    shutil.rmtree(mdir)
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
    return {"ok": True, "bank_refs_removed": removed}


@app.get("/api/meetings/{slug}/bundle")
def get_bundle(slug: str):
    mdir = _mdir(slug)
    transcript = _read_json(mdir / "transcript.spk.json", [])
    slides = _read_json(mdir / "slides.json", [])
    minutes_html, topics = _minutes_html(mdir, slug)
    src = _source(mdir)
    samples_dir = mdir / "samples"
    samples = sorted(p.stem for p in samples_dir.glob("*.wav")) if samples_dir.is_dir() else []
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
        "has_audio": (mdir / "audio.wav").is_file(),
        "has_video": bool(src.get("mp4") and Path(src["mp4"]).is_file()),
        "duration": max((t.get("end", 0) for t in transcript), default=0),
        "speaker_count": len({t.get("speaker") for t in transcript if t.get("speaker")}),
        "transcript_revision": assistant.revision(mdir / "transcript.spk.json"),
        "minutes_revision": assistant.revision(_minutes_file(mdir)) if _minutes_file(mdir) else None,
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
            transcript, _assistant_message(req.message), req.turn_indexes,
            req.transcript_revision, req.history, DRY_RUN)
    except assistant.AssistantError as exc:
        _assistant_http_error(exc)


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
        return assistant.apply_minutes_edit(minutes, req.proposal_id)
    except assistant.AssistantError as exc:
        _assistant_http_error(exc)


@app.post("/api/meetings/{slug}/assistant/edit/undo")
def assistant_edit_undo(slug: str, req: AssistantApplyReq):
    mdir = _mdir(slug)
    minutes = _minutes_file(mdir)
    if minutes is None:
        raise HTTPException(400, "没有可恢复的纪要")
    try:
        return assistant.undo_minutes_edit(minutes, req.proposal_id)
    except assistant.AssistantError as exc:
        _assistant_http_error(exc)


@app.get("/api/meetings/{slug}/media/audio")
def media_audio(slug: str):
    p = _mdir(slug) / "audio.wav"
    if not p.is_file():
        raise HTTPException(404, "没有音频")
    return FileResponse(p, media_type="audio/wav")


@app.get("/api/meetings/{slug}/media/video")
def media_video(slug: str):
    src = _source(_mdir(slug))
    mp4 = src.get("mp4")
    if not mp4 or not Path(mp4).is_file():
        raise HTTPException(404, "没有源视频")
    return FileResponse(mp4, media_type="video/mp4")


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
        cands = [{"name": p.get("name", ""), "aliases": p.get("aliases", [])}
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
            person = next((p for p in bank["persons"]
                           if p["name"].strip().lower() == name.strip().lower()), None)
            how = "bank"
            if person is None:
                person = vb.add_person(bank, name.strip())
                how = "新建"
        else:
            org = vb.load_orgchart(BANK_DIR)
            person, how = _resolve_or_409(bank, name, orgchart=org)
        voice["person_id"] = person["id"]
        vb.save_bank(BANK_DIR, bank)
        return person["name"], (how if isinstance(how, str) else "?")


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
    persons = [{"id": p["id"], "name": p["name"], "aliases": p.get("aliases", []),
                "created": p.get("created", ""),
                "voices": sum(1 for v in bank["voices"] if v.get("person_id") == p["id"])}
               for p in bank["persons"]]
    return {"persons": persons, "voices": voices}


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
        return {"ok": True, "name": person["name"], "aliases": person["aliases"]}


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

@app.get("/api/orgchart")
def get_orgchart():
    return {"entries": vb.load_orgchart(BANK_DIR)}


class OrgPut(BaseModel):
    entries: list[dict]


@app.put("/api/orgchart")
def put_orgchart(req: OrgPut):
    """前端按 leader 字段组装树，保存时整体回写扁平 list。"""
    entries = []
    for e in req.entries:
        name = str(e.get("name", "")).strip()
        if not name:
            raise HTTPException(400, "存在空名字条目")
        entries.append({
            "name": name,
            "aliases": [str(a) for a in e.get("aliases", []) if str(a).strip()],
            "title": str(e.get("title", "")),
            "team": str(e.get("team", "")),
            "leader": str(e.get("leader", "")),
            "note": str(e.get("note", "")),
        })
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
    return {"entries": _read_json(p, []), "has_draft": True}


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
    return FileResponse(STATIC / "index.html")


@app.get("/admin")
def admin():
    return FileResponse(STATIC / "admin.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")

_load_jobs()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("MEETING_WEB_PORT", 8899)),
                log_level="info")
