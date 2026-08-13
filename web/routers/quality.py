"""纪要质量人工验收。
服务 schema：meeting-minutes-evaluation/v1、meeting-minutes-evidence/v1、
meeting-generation/v1。"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import evaluation_service as evaluation
import meeting_generation
from deps import (EVALUATIONS_DIR, EVALUATION_LOCK, _current_evidence,
                  _minutes_file, _mdir)

router = APIRouter()


class QualityReviewReq(BaseModel):
    label: str
    note: str = Field(default="", max_length=1000)
    claim_fingerprint: str


def _evaluation_path(slug: str) -> Path:
    # slug 已由 _mdir 校验为 MEETINGS 的直接子目录名。
    return EVALUATIONS_DIR / f"{slug}.json"


def _quality_payload(slug: str, mdir: Path) -> dict:
    if meeting_generation.document_state(mdir, _minutes_file(mdir) is not None) == "draft":
        store = evaluation.load_store(_evaluation_path(slug), slug)
        return evaluation.build_payload(slug, {}, store, "draft")
    evidence = _current_evidence(mdir)
    if evidence:
        evidence_state = "ready"
    elif (mdir / "minutes.evidence.json").is_file():
        evidence_state = "stale"
    else:
        evidence_state = "missing"
    store = evaluation.load_store(_evaluation_path(slug), slug)
    return evaluation.build_payload(slug, evidence, store, evidence_state)


@router.get("/api/meetings/{slug}/quality")
def get_quality_review(slug: str):
    """返回当前结论与本机人工验收；不运行模型，也不修改正式纪要。"""
    mdir = _mdir(slug)
    return _quality_payload(slug, mdir)


@router.put("/api/meetings/{slug}/quality/claims/{claim_id}")
def put_quality_review(slug: str, claim_id: str, req: QualityReviewReq):
    mdir = _mdir(slug)
    if meeting_generation.document_state(mdir, _minutes_file(mdir) is not None) == "draft":
        raise HTTPException(409, "语音草稿仍在补充屏幕资料，终稿后再审计结论")
    evidence = _current_evidence(mdir)
    if not evidence:
        raise HTTPException(409, "纪要依据缺失或已过期，请先重新生成纪要")
    claim = next((item for item in evidence.get("claims", []) if item.get("id") == claim_id), None)
    if claim is None:
        raise HTTPException(404, "结论不存在")
    current_fingerprint = evaluation.claim_fingerprint(claim, evidence)
    if req.claim_fingerprint != current_fingerprint:
        raise HTTPException(409, "结论或依据已变化，请刷新后重新判断")
    try:
        with EVALUATION_LOCK:
            evaluation.save_review(
                _evaluation_path(slug), slug, evidence, claim, req.label, req.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _quality_payload(slug, mdir)
