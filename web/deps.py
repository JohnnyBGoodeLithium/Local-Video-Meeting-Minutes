"""web 层共享依赖：路径/环境常量、锁、Markdown 渲染器与会议文件助手。

只放纯函数与常量：作业状态在 job_store，路由在 routers/。
本模块只依赖 bin/ 与 web/ 的 service 模块，不反向依赖 job_store/routers。
"""

import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

from fastapi import HTTPException

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
import assistant_service as assistant  # noqa: E402
import meeting_artifact as artifact  # noqa: E402

from markdown_it import MarkdownIt  # noqa: E402

MD = MarkdownIt("default", {"html": False})

BANK_LOCK = threading.Lock()      # bank.json / orgchart.json 写操作串行化
EVALUATION_LOCK = threading.Lock()  # 本地人工验收事件串行化
STORAGE_LOCK = threading.Lock()     # 会议缓存清理与大小读取串行化

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".wma", ".aiff"}
VTT_EXT = {".vtt"}
ORG_FILE_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


# ---------------------------------------------------------------- 工具

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


def _storage_file_size(paths: list[Path]) -> int:
    return sum(path.stat().st_size for path in paths
               if path.is_file() and not path.is_symlink())


def _meeting_storage(mdir: Path) -> dict:
    """按母版、阅读资产、可再生缓存返回逻辑大小，不暴露会议正文。"""
    all_files = [path for path in mdir.rglob("*") if path.is_file() and not path.is_symlink()]
    original = sorted({
        *[path for pattern in ("source_video.*", "source_audio.*") for path in mdir.glob(pattern)
          if path.is_file()],
        *([mdir / "source.vtt"] if (mdir / "source.vtt").is_file() else []),
    })
    # 兼容旧录音会议：没有独立母版时，audio.wav 本身必须被保护。
    if not any(path.name.startswith(("source_video.", "source_audio.")) for path in original):
        if (mdir / "audio.wav").is_file():
            original.append(mdir / "audio.wav")

    canonical_media = any(path.name.startswith(("source_video.", "source_audio."))
                          for path in original)
    cache_groups: list[dict] = []
    work_audio = mdir / "audio.wav"
    if canonical_media and work_audio.is_file() and (mdir / "transcript.spk.json").is_file():
        cache_groups.append({"id": "work_audio", "label": "模型 PCM 工作音轨",
                             "files": [work_audio], "regenerates_from": "原始母版"})
    full_frames = sorted((mdir / "slides").glob("full_*")) if (mdir / "slides").is_dir() else []
    if full_frames and (mdir / "page_desc.json").is_file():
        cache_groups.append({"id": "vl_frames", "label": "VL 高分辨率工作帧",
                             "files": full_frames, "regenerates_from": "原始母版"})
    rag_files = ([path for path in (mdir / ".rag").rglob("*")
                  if path.is_file() and not path.is_symlink()]
                 if (mdir / ".rag").is_dir() else [])
    if rag_files:
        cache_groups.append({"id": "rag", "label": "本地检索索引",
                             "files": rag_files, "regenerates_from": "逐字稿与证据"})
    topic_work = mdir / ".topic-map-work.json"
    if topic_work.is_file():
        cache_groups.append({"id": "topic_work", "label": "会议脉络生成检查点",
                             "files": [topic_work], "regenerates_from": "逐字稿与证据"})

    original_set = set(original)
    cache_set = {path for group in cache_groups for path in group["files"]}
    reading = [path for path in all_files if path not in original_set and path not in cache_set]
    original_bytes = _storage_file_size(original)
    reading_bytes = _storage_file_size(reading)
    cache_bytes = _storage_file_size(list(cache_set))
    return {
        "schema": "meeting-storage/v1",
        "logical_bytes": original_bytes + reading_bytes + cache_bytes,
        "original": {"bytes": original_bytes, "files": len(original), "protected": True},
        "reading": {"bytes": reading_bytes, "files": len(reading)},
        "cache": {
            "bytes": cache_bytes, "files": len(cache_set), "reclaimable": bool(cache_set),
            "groups": [{"id": group["id"], "label": group["label"],
                        "bytes": _storage_file_size(group["files"]),
                        "files": len(group["files"]),
                        "regenerates_from": group["regenerates_from"]}
                       for group in cache_groups],
        },
        "policy": {
            "original": "受保护，不会被智能清理删除",
            "reading": "默认保留，支持离线阅读与证据核对",
            "cache": "可从母版或文本证据重新生成；当前由用户触发清理",
        },
    }


def _clean_meeting_cache(mdir: Path) -> dict:
    before = _meeting_storage(mdir)
    removed_files = 0
    for group in before["cache"]["groups"]:
        if group["id"] == "work_audio":
            targets = [mdir / "audio.wav"]
        elif group["id"] == "vl_frames":
            targets = sorted((mdir / "slides").glob("full_*"))
        elif group["id"] == "rag":
            targets = [mdir / ".rag"]
        elif group["id"] == "topic_work":
            targets = [mdir / ".topic-map-work.json"]
        else:
            targets = []
        for target in targets:
            if target.is_dir() and target == mdir / ".rag":
                removed_files += sum(1 for path in target.rglob("*") if path.is_file())
                shutil.rmtree(target)
            elif target.is_file() and target.is_relative_to(mdir):
                target.unlink()
                removed_files += 1
    after = _meeting_storage(mdir)
    return {"ok": True, "removed_files": removed_files,
            "reclaimed_logical_bytes": max(0, before["logical_bytes"] - after["logical_bytes"]),
            "storage": after}


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
    return artifact.project_action_semantics(
        evidence, minutes.read_text(encoding="utf-8"))


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


# ---------------------------------------------------------------- 纪要渲染

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
    evidence = _current_evidence(mdir)
    reading_text = artifact.minutes_reading_markdown(
        full_text, evidence, include_topic_section=False)
    reading_text = artifact.markdown_with_evidence_links(reading_text, evidence)
    html = MD.render(reading_text)
    # 纪要里的 slides/ 相对图片 → 本服务 file 路由
    html = html.replace('src="slides/', f'src="/api/meetings/{slug}/file?path=slides/')
    return html, topics


def _minutes_reading_source(mdir: Path) -> tuple[str, dict]:
    minutes_path = _minutes_file(mdir)
    if minutes_path is None:
        return "", _current_evidence(mdir)
    evidence = _current_evidence(mdir)
    full_text = artifact.normalize_minutes_markdown(minutes_path.read_text(encoding="utf-8"))
    return artifact.minutes_reading_markdown(
        full_text, evidence, include_topic_section=False), evidence


def _render_minutes_language(markdown: str, evidence: dict, target: str) -> str:
    linked = artifact.markdown_with_evidence_links(
        markdown, evidence, label="Evidence" if target == "en" else "依据")
    return MD.render(linked)
