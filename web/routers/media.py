"""会议媒体与文件流。服务 schema：无（仅媒体/文件字节流）。"""

import mimetypes
import re

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

import voice_bank as vb
import caption_projection
import caption_service
from deps import (BANK_DIR, _audio_path, _current_evidence, _meeting_identity, _mdir,
                  _safe, _video_path)

router = APIRouter()


@router.get("/api/meetings/{slug}/media/audio")
def media_audio(slug: str):
    p = _audio_path(_mdir(slug))
    if p is None:
        raise HTTPException(404, "没有音频")
    media_type = mimetypes.guess_type(p.name)[0] or "audio/wav"
    return FileResponse(p, media_type=media_type)


@router.get("/api/meetings/{slug}/media/video")
def media_video(slug: str):
    p = _video_path(_mdir(slug))
    if p is None:
        raise HTTPException(404, "没有源视频")
    media_type = mimetypes.guess_type(p.name)[0] or "video/mp4"
    return FileResponse(p, media_type=media_type)


@router.get("/api/meetings/{slug}/captions/{track}.vtt")
def media_captions(slug: str, track: str,
                   target: str = Query("en", pattern="^(en|zh-CN)$")):
    mode = track.removesuffix(".vtt")
    if mode not in {"source", "translation"}:
        raise HTTPException(404, "Caption track unavailable")
    mdir = _mdir(slug)
    translation, cues = caption_service.payload(
        mdir, str(_meeting_identity(slug).get("title") or slug),
        _current_evidence(mdir), BANK_DIR, target)
    if mode == "translation" and translation.get("state") != "ready":
        raise HTTPException(409, "Translation is unavailable or awaiting revision refresh")
    return Response(caption_projection.render_vtt(
        cues, mode=mode, content_type=str(_meeting_identity(slug).get("content_type") or "meeting")),
        media_type="text/vtt", headers={"Cache-Control": "private, max-age=300"})


@router.get("/api/meetings/{slug}/file")
def meeting_file(slug: str, path: str = Query(...)):
    mdir = _mdir(slug)
    p = (mdir / path).resolve()
    if not p.is_file() or not p.is_relative_to(mdir):
        raise HTTPException(404, "文件不存在")
    return FileResponse(p)


@router.get("/api/meetings/{slug}/samples/{filename}")
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
