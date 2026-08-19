"""逐字稿音频复核摘要、人工文本修正与撤销。"""

import json
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import transcript_service
from deps import (MEETING_META_LOCK, TRANSCRIPT_EDIT_LOCK, _current_evidence,
                  _mdir, _now, _read_json)
from job_store import JOBS


router = APIRouter()


class TranscriptEditReq(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    transcript_revision: str | None = None


def _ensure_idle(slug: str) -> None:
    if any(job.get("meeting") == slug and job.get("status") in {"queued", "running"}
           for job in JOBS.values()):
        raise HTTPException(409, "这场会议仍在处理，完成后才能修正逐字稿")


def _touch(mdir) -> None:
    path = mdir / "meta.json"
    with MEETING_META_LOCK:
        meta = _read_json(path, {})
        if not isinstance(meta, dict):
            meta = {}
        meta["updated_at"] = _now()
        temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        temp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temp, path)


@router.get("/api/meetings/{slug}/transcript-review")
def transcript_review(slug: str):
    mdir = _mdir(slug)
    return transcript_service.project_review(mdir, bool(_current_evidence(mdir)))


@router.patch("/api/meetings/{slug}/transcript/{index}")
def edit_transcript_turn(slug: str, index: int, req: TranscriptEditReq):
    mdir = _mdir(slug)
    _ensure_idle(slug)
    try:
        with TRANSCRIPT_EDIT_LOCK:
            result = transcript_service.apply_text_edit(
                mdir, index, req.text, req.transcript_revision, method="human")
            if result.get("changed"):
                _touch(mdir)
    except IndexError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, **result,
            "review": transcript_service.project_review(mdir, bool(_current_evidence(mdir)))}


@router.post("/api/meetings/{slug}/transcript/undo")
def undo_transcript_edit(slug: str):
    mdir = _mdir(slug)
    _ensure_idle(slug)
    try:
        with TRANSCRIPT_EDIT_LOCK:
            result = transcript_service.undo_latest(mdir)
            _touch(mdir)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {**result,
            "review": transcript_service.project_review(mdir, bool(_current_evidence(mdir)))}
