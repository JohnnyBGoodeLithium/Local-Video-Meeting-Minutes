"""健康检查与静态页。服务 schema：无（仅健康元数据与静态 HTML）。"""

from fastapi import APIRouter
from fastapi.responses import FileResponse

from deps import DATA_ROOT, DRY_RUN, MEETINGS, PY, STATIC, assistant
from job_store import JOBS

router = APIRouter()


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
