"""健康检查与静态页。服务 schema：无（仅健康元数据与静态 HTML）。"""

import os
from urllib.parse import urlparse

from fastapi import APIRouter
from fastapi.responses import FileResponse

from deps import DATA_ROOT, DRY_RUN, MEETINGS, PY, STATIC, assistant
from job_store import JOBS
from product_version import PRODUCT_VERSION

router = APIRouter()


def _knowledge_base_config() -> dict:
    raw = os.environ.get("MEETING_KB_URL", "").strip().rstrip("/")
    parsed = urlparse(raw)
    safe = bool(raw and parsed.scheme in {"http", "https"} and parsed.hostname
                and not parsed.username and not parsed.password)
    return {
        "provider": os.environ.get("MEETING_KB_PROVIDER", "weknora") if safe else None,
        "configured": safe,
        "url": raw if safe else None,
    }


@router.get("/api/health")
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
        "product": {"name": "Meeting Minutes", "version": PRODUCT_VERSION},
        "integrations": {"knowledge_base": _knowledge_base_config()},
        "assistant": {"model": assistant.LLM_MODEL, "local_only": not assistant.ALLOW_REMOTE,
                      "rag": assistant.rag_service.RAG_VERSION,
                      "retrieval_models": assistant.rag_service.retrieval_models.status()},
    }


# ---------------------------------------------------------------- 静态页

@router.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@router.get("/admin")
def admin():
    return FileResponse(STATIC / "admin.html", headers={"Cache-Control": "no-store"})


@router.get("/product")
def product():
    return FileResponse(STATIC / "product.html", headers={"Cache-Control": "no-store"})
