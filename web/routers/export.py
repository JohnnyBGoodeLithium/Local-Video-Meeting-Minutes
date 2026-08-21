"""MeetingPack 静态导出与导出前预检。
服务 schema：meetingpack/v5（导出包）、meeting-minutes-evidence/v1、
meeting-generation/v1。"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

import export_meeting as meeting_export
import meeting_generation
from product_version import PRODUCT_VERSION, PRODUCT_VERSION_LABEL
from deps import (BANK_DIR, _current_evidence, _evidence_state,
                  _meeting_identity, _minutes_file, _mdir, _read_json, _safe,
                  _video_path)

router = APIRouter()


def _download_filename(ident: dict, now: datetime | None = None) -> str:
    """可读且不重名的导出名：会议日期 + 产品版本 + 本地导出时间。"""
    base = _safe(ident.get("title") or "") or "meeting"
    meeting_date = f"_{ident['date']}" if ident.get("date") else ""
    stamp = (now or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")
    return f"{base}{meeting_date}_{PRODUCT_VERSION_LABEL}_{stamp}.meetingpack.zip"


@router.get("/api/meetings/{slug}/export")
def export_meeting_pack(slug: str, media: str = Query("none", pattern="^(none|audio|video)$")):
    """生成静态 MeetingPack；逐字稿形成后即可导出核听快照。"""
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
    filename = _download_filename(ident)
    return FileResponse(
        archive, media_type="application/zip", filename=filename,
        background=BackgroundTask(archive.unlink, missing_ok=True))


@router.get("/api/meetings/{slug}/export/preflight")
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
        mdir / "meeting.topic-map.json",
        _minutes_file(mdir),
    ]
    base_bytes = 260_000  # viewer、manifest、README 与导出索引的保守开销
    for path in base_paths:
        if path and path.is_file():
            base_bytes += path.stat().st_size
    slides_dir = mdir / "slides"
    video = _video_path(mdir)
    slide_images = []
    analysis_bytes = 0
    for page in slides:
        image = slides_dir / str(page.get("image") or "")
        if image.is_file() and image not in slide_images:
            slide_images.append(image)
        number = page.get("page")
        analysis_frame = slides_dir / f"full_{int(number):02d}.jpg" if number is not None else None
        if analysis_frame and analysis_frame.is_file():
            analysis_bytes += analysis_frame.stat().st_size
        elif image.is_file():
            # 缓存被清理后，正式导出会从同一时间点恢复原生分辨率 JPEG。
            # 预检用逻辑页的 2.5 倍作保守估计；没有视频时使用逻辑页 JPEG。
            analysis_bytes += (max(image.stat().st_size, int(image.stat().st_size * 2.5))
                               if video else image.stat().st_size)
    base_bytes += analysis_bytes
    audio = meeting_export._media_source(mdir, "audio")
    audio_bytes = audio.stat().st_size if audio else 0
    video_bytes = video.stat().st_size if video else 0
    duration = max((float(turn.get("end", 0)) for turn in transcript), default=0)
    audio_export_bytes = int(duration * 5_300) if audio else 0  # AAC 40kbps + container
    video_export_bytes = (min(video_bytes, int(duration * 35_000))
                          if video else 0)  # 720p/10fps CRF30 的保守估计
    document_state = meeting_generation.document_state(
        mdir, bool(transcript and _minutes_file(mdir)))
    return {
        **ident,
        "product_version": PRODUCT_VERSION,
        "filename_pattern": (
            f"{_safe(ident['title']) or 'meeting'}"
            f"{'_' + ident['date'] if ident.get('date') else ''}"
            f"_{PRODUCT_VERSION_LABEL}_YYYYMMDD-HHMMSS.meetingpack.zip"),
        "document_state": document_state,
        "export_mode": "final" if document_state == "ready" else "review_snapshot",
        "generation": meeting_generation.load(mdir),
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
            "audio": {"available": bool(audio), "source_bytes": audio_bytes,
                      "export_bytes": audio_export_bytes, "format": "AAC 40kbps"},
            "video": {"available": bool(video), "source_bytes": video_bytes,
                      "export_bytes": video_export_bytes, "format": "H.264 720p / 10fps"},
        },
        "estimated_bytes": {
            "none": base_bytes,
            "audio": base_bytes + audio_export_bytes,
            "video": base_bytes + video_export_bytes,
        },
    }
