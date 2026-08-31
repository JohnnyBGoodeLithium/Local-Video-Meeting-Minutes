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

from deps import MEETING_META_LOCK, _content_type, _mdir, _now, _read_json
from meeting_core import photos as meeting_photos


router = APIRouter()


class PhotoAlignmentRequest(BaseModel):
    seconds: float | None = None


class PhotoUpdateRequest(BaseModel):
    title: str


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
        _touch(mdir)
        return {"ok": True, **result}
    except meeting_photos.PhotoError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


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
