"""会议关键字：revision 绑定的派生清单，终稿后自动补齐。
服务 schema：meeting-keywords/v1。"""

from fastapi import APIRouter, HTTPException, Query

import keyword_service as keywords
import meeting_generation
from deps import (BANK_LOCK, DRY_RUN, MEETINGS, assistant, _current_evidence,
                  _meeting_identity, _minutes_file, _mdir, _now)
from job_store import EXEC, JOBS, _new_job, _save_job, _set_status

router = APIRouter()


def _keywords_payload(slug: str, mdir) -> dict:
    if _minutes_file(mdir) is None:
        raise HTTPException(404, "没有会议纪要")
    return keywords.keywords_payload(mdir)


def _run_keywords_job(job: dict, mdir, title: str) -> None:
    if job.get("cancel_requested"):
        return
    _set_status(job, "running", started=_now(), stage="提取会议关键字",
                progress={"done": 0, "total": 1})

    def cancelled() -> bool:
        return bool(job.get("cancel_requested"))

    try:
        document = keywords.generate_keywords(
            mdir, title, _current_evidence(mdir), dry_run=DRY_RUN,
            should_cancel=cancelled)
    except keywords.KeywordCancelled:
        if job.get("status") != "cancelled":
            _set_status(job, "cancelled", finished=_now(), rc=None)
        return
    except (keywords.KeywordError, assistant.AssistantError):
        job.setdefault("log", []).append("[error] 关键字提取失败")
        _set_status(job, "failed", finished=_now(), rc=None)
        return
    _set_status(job, "done", finished=_now(), rc=0,
                progress={"done": 1, "total": 1},
                result={"artifact": "keywords",
                        "count": len(document.get("keywords", [])),
                        "dry_run": DRY_RUN})


def _active_keywords_job(slug: str):
    return next((job for job in JOBS.values()
                 if job.get("kind") == "keywords" and job.get("meeting") == slug
                 and job.get("status") in {"queued", "running"}), None)


@router.get("/api/meetings/{slug}/keywords")
def get_keywords(slug: str):
    return _keywords_payload(slug, _mdir(slug))


@router.get("/api/keywords/index")
def get_keywords_index():
    """全局关键字索引：请求时重建，N 个小 JSON 不引入缓存复杂度。"""
    return keywords.global_index(MEETINGS)


@router.get("/api/meetings/{slug}/keywords/related")
def get_related_keywords(slug: str, limit: int = Query(8, ge=1, le=50)):
    """与目标会议共享关键字的其他会议；shared 即导出弹窗展示的推荐理由。"""
    _mdir(slug)
    return {"slug": slug, "related": keywords.related(MEETINGS, slug, limit=limit)}


@router.post("/api/meetings/{slug}/keywords")
def create_keywords(slug: str, force: bool = Query(False)):
    mdir = _mdir(slug)
    current = _keywords_payload(slug, mdir)
    if current["state"] == "ready" and not force:
        return {"id": None, "kind": "keywords", "status": "done", "cached": True,
                "meeting": slug, "result": {"count": len(current.get("keywords", []))}}
    existing = _active_keywords_job(slug)
    if existing:
        return dict(existing)
    job = _new_job("keywords", meeting=slug, progress={"done": 0, "total": 1})
    response = dict(job)
    EXEC.submit(_run_keywords_job, job, mdir, _meeting_identity(slug)["title"])
    return response


def auto_keywords_after_ready(slug: str, mdir) -> list[str]:
    """终稿就绪后低优先级补齐关键字；与自动翻译同一触发时机。"""
    if _minutes_file(mdir) is None or meeting_generation.document_state(mdir, True) != "ready":
        return []
    payload = keywords.keywords_payload(mdir)
    if payload.get("state") not in {"missing", "stale", "failed", "cancelled"}:
        return []
    if _active_keywords_job(slug):
        return []
    job = _new_job("keywords", meeting=slug, auto=True,
                   progress={"done": 0, "total": 1})
    EXEC.submit(_run_keywords_job, job, mdir, _meeting_identity(slug)["title"])
    return [job["id"]]
