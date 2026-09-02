"""会议现场照片导入与可信时间对齐。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from deps import MEETING_META_LOCK, PY, ROOT, _content_type, _mdir, _now, _read_json
from job_store import EXEC, JOBS, _new_job, _run_pipeline
from meeting_core import photos as meeting_photos


router = APIRouter()


class PhotoAlignmentRequest(BaseModel):
    seconds: float | None = None


class PhotoUpdateRequest(BaseModel):
    title: str


class PhotoAnalysisRequest(BaseModel):
    photo_ids: list[str]


def _job_projection(job: dict | None) -> dict | None:
    """Return only safe state needed by the upload UI; never expose the command/path."""
    if not job:
        return None
    return {key: job.get(key) for key in ("id", "status", "kind", "meeting")}


def _minutes_sync_available(mdir: Path) -> bool:
    """Only offer immediate sync when it can reuse a complete existing source set."""
    if not (mdir / "transcript.spk.json").is_file() or not any(
        (mdir / name).is_file() for name in ("minutes.md", "minutes.spk.md")
    ):
        return False
    slides_path = mdir / "slides.json"
    if not slides_path.is_file():
        return (mdir / "transcript.txt").is_file()
    try:
        timeline = json.loads(slides_path.read_text(encoding="utf-8"))
        cache = json.loads((mdir / "page_desc.json").read_text(encoding="utf-8"))
        required = {int(item["page"]) for item in timeline
                    if item.get("kind", "slide") == "slide"
                    and item.get("page") is not None}
        available = {int(key) for key, value in (cache.get("desc") or {}).items()
                     if str(key).isdigit() and str(value or "").strip()}
    except (OSError, ValueError, TypeError, KeyError):
        return False
    return bool(required) and required <= available


def _queue_analysis(slug: str, mdir: Path, photo_ids: list[str]) -> dict | None:
    ids = list(dict.fromkeys(str(value or "").strip() for value in photo_ids))
    ids = [value for value in ids if value]
    if not ids:
        return None
    active = [job for job in JOBS.values()
              if job.get("meeting") == slug and job.get("kind") == "photo_analysis"
              and job.get("status") in {"queued", "running"}]
    covered = {str(photo_id) for job in active for photo_id in job.get("photo_ids") or []}
    ids = [value for value in ids if value not in covered]
    if not ids:
        return active[0] if active else None
    meeting_photos.set_analysis_state(mdir, ids, "queued")
    sync_minutes = _minutes_sync_available(mdir)
    command = [str(PY), str(ROOT / "bin" / "analyze_photos.py"), str(mdir),
               "--photo-ids", ",".join(ids)]
    if sync_minutes:
        command.append("--sync-minutes")
    outputs = {
        "transcript": "ready" if (mdir / "transcript.spk.json").is_file() else "pending",
        "speaker_navigation": "ready" if (mdir / "transcript.spk.json").is_file() else "pending",
        "final_minutes": "partial" if sync_minutes else (
            "ready" if any((mdir / name).is_file()
                           for name in ("minutes.md", "minutes.spk.md")) else "pending"),
        "visuals": "partial",
    }
    job = _new_job(
        "photo_analysis", route="photos", cmd=command, meeting=slug,
        content_type="meeting", photo_ids=ids, sync_minutes=sync_minutes,
        followup_topic_map=sync_minutes, available_outputs=outputs)
    EXEC.submit(_run_pipeline, job)
    return job


def _duration(mdir: Path) -> float:
    turns = _read_json(mdir / "transcript.spk.json", [])
    return max((float(turn.get("end") or 0) for turn in turns), default=0.0)


def _touch(mdir: Path) -> None:
    path = mdir / "meta.json"
    with MEETING_META_LOCK:
        meta = _read_json(path, {})
        if not isinstance(meta, dict):
            meta = {}
        meta["updated_at"] = _now()
        temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        temp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temp, path)


@router.post("/api/meetings/{slug}/photos")
async def add_photos(
    slug: str,
    files: list[UploadFile] = File(...),
    mode: str = Form("unlocated"),
    meeting_start: str = Form(""),
    anchor_seconds: str = Form(""),
    defer_analysis: str = Form(""),
):
    mdir = _mdir(slug)
    meta = _read_json(mdir / "meta.json", {})
    if _content_type(meta.get("content_type")) != "meeting":
        raise HTTPException(400, "现场照片只适用于会议；媒体内容请继续使用画面解析")
    if not files:
        raise HTTPException(400, "请选择至少一张照片")
    try:
        anchor = float(anchor_seconds) if anchor_seconds.strip() else None
    except ValueError as exc:
        raise HTTPException(400, "播放器时间无效") from exc

    temp_dir = Path(tempfile.mkdtemp(prefix="meeting-photos-"))
    sources: list[tuple[Path, str]] = []
    try:
        for index, upload in enumerate(files, start=1):
            name = Path(upload.filename or f"photo-{index}.jpg").name
            suffix = Path(name).suffix.lower()
            temp = temp_dir / f"{index:04d}{suffix}"
            size = 0
            async with aiofiles.open(temp, "wb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > meeting_photos.MAX_FILE_BYTES:
                        raise meeting_photos.PhotoError("单张照片不能超过 32 MB")
                    await handle.write(chunk)
            sources.append((temp, name))
        result = meeting_photos.import_photos(
            mdir, sources, mode=mode, duration=_duration(mdir),
            meeting_start_iso=meeting_start.strip() or None,
            anchor_seconds=anchor)
        analysis_job = None
        if result["created_ids"] and not defer_analysis.strip():
            analysis_job = _queue_analysis(slug, mdir, result["created_ids"])
        _touch(mdir)
        return {"ok": True, **result,
                "analysis_job": _job_projection(analysis_job)}
    except meeting_photos.PhotoError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.post("/api/meetings/{slug}/photos/analyze")
def analyze_photos(slug: str, request: PhotoAnalysisRequest):
    mdir = _mdir(slug)
    document = meeting_photos.load(mdir)
    known = {str(item.get("id") or "") for item in document.get("photos", [])}
    ids = list(dict.fromkeys(str(value or "").strip() for value in request.photo_ids))
    if not ids or any(value not in known for value in ids):
        raise HTTPException(400, "请选择有效的现场资料")
    try:
        job = _queue_analysis(slug, mdir, ids)
    except meeting_photos.PhotoError as exc:
        raise HTTPException(400, str(exc)) from exc
    _touch(mdir)
    return {"ok": True, "job": _job_projection(job)}


@router.patch("/api/meetings/{slug}/photos/{photo_id}/alignment")
def align_photo(slug: str, photo_id: str, request: PhotoAlignmentRequest):
    mdir = _mdir(slug)
    try:
        record = meeting_photos.set_alignment(
            mdir, photo_id, request.seconds, duration=_duration(mdir))
    except meeting_photos.PhotoError as exc:
        raise HTTPException(400, str(exc)) from exc
    _touch(mdir)
    return {"ok": True, "photo": record}


@router.patch("/api/meetings/{slug}/photos/{photo_id}")
def update_photo(slug: str, photo_id: str, request: PhotoUpdateRequest):
    mdir = _mdir(slug)
    try:
        record = meeting_photos.set_title(mdir, photo_id, request.title)
    except meeting_photos.PhotoError as exc:
        raise HTTPException(400, str(exc)) from exc
    _touch(mdir)
    return {"ok": True, "photo": record}


@router.delete("/api/meetings/{slug}/photos/{photo_id}")
def remove_photo(slug: str, photo_id: str):
    mdir = _mdir(slug)
    try:
        result = meeting_photos.delete_photo(mdir, photo_id)
    except meeting_photos.PhotoError as exc:
        raise HTTPException(400, str(exc)) from exc
    _touch(mdir)
    return {"ok": True, **result}
