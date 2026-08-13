"""本地会议助手：问答、RAG 检索与纪要编辑提案。
服务 schema：meeting-rag/evidence-hybrid-v1、meeting-minutes-evidence/v1、
meeting-generation/v1。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import meeting_generation
from deps import DRY_RUN, assistant, _minutes_file, _mdir, _refresh_evidence

router = APIRouter()


class AssistantChatReq(BaseModel):
    message: str
    turn_indexes: list[int] = Field(default_factory=list)
    transcript_revision: str | None = None
    history: list[dict] = Field(default_factory=list)


class AssistantEditReq(BaseModel):
    message: str
    turn_indexes: list[int] = Field(default_factory=list)
    transcript_revision: str | None = None
    minutes_revision: str | None = None
    target_heading: str | None = None


class AssistantApplyReq(BaseModel):
    proposal_id: str


class RagSearchReq(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    turn_indexes: list[int] = Field(default_factory=list, max_length=30)


def _assistant_message(text: str) -> str:
    value = text.strip()
    if not value:
        raise HTTPException(400, "请输入问题或修改要求")
    if len(value) > 8000:
        raise HTTPException(400, "单次输入不能超过 8000 个字符")
    return value


def _assistant_http_error(exc: assistant.AssistantError):
    raise HTTPException(exc.status, str(exc)) from exc


@router.post("/api/meetings/{slug}/assistant/chat")
def assistant_chat(slug: str, req: AssistantChatReq):
    mdir = _mdir(slug)
    transcript = mdir / "transcript.spk.json"
    if not transcript.is_file():
        raise HTTPException(400, "没有逐字稿，无法进行会议问答")
    try:
        return assistant.answer_question(
            mdir, _assistant_message(req.message), req.turn_indexes,
            req.transcript_revision, req.history, DRY_RUN)
    except assistant.AssistantError as exc:
        _assistant_http_error(exc)


@router.post("/api/meetings/{slug}/rag/search")
def rag_search(slug: str, req: RagSearchReq):
    """只运行检索、不调用 LLM；用于检查召回来源和后续轻量 Viewer 接入。"""
    mdir = _mdir(slug)
    if not (mdir / "transcript.spk.json").is_file():
        raise HTTPException(400, "没有逐字稿，无法检索")
    try:
        result = assistant.rag_service.retrieve(mdir, req.query.strip(), req.turn_indexes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    result.pop("context", None)
    return result


@router.post("/api/meetings/{slug}/assistant/edit/preview")
def assistant_edit_preview(slug: str, req: AssistantEditReq):
    mdir = _mdir(slug)
    if meeting_generation.document_state(mdir, _minutes_file(mdir) is not None) == "draft":
        raise HTTPException(409, "语音草稿正在补充屏幕资料；终稿完成后才能修改纪要")
    transcript = mdir / "transcript.spk.json"
    minutes = _minutes_file(mdir)
    if not transcript.is_file() or minutes is None:
        raise HTTPException(400, "需要逐字稿和纪要才能生成修改预览")
    try:
        return assistant.preview_minutes_edit(
            minutes, transcript, _assistant_message(req.message), req.turn_indexes,
            req.transcript_revision, req.minutes_revision, req.target_heading, DRY_RUN)
    except assistant.AssistantError as exc:
        _assistant_http_error(exc)


@router.post("/api/meetings/{slug}/assistant/edit/apply")
def assistant_edit_apply(slug: str, req: AssistantApplyReq):
    mdir = _mdir(slug)
    if meeting_generation.document_state(mdir, _minutes_file(mdir) is not None) == "draft":
        raise HTTPException(409, "语音草稿正在升级，不能应用旧修改提案")
    minutes = _minutes_file(mdir)
    if minutes is None:
        raise HTTPException(400, "没有可修改的纪要")
    try:
        result = assistant.apply_minutes_edit(minutes, req.proposal_id)
        _refresh_evidence(mdir)
        return result
    except assistant.AssistantError as exc:
        _assistant_http_error(exc)


@router.post("/api/meetings/{slug}/assistant/edit/undo")
def assistant_edit_undo(slug: str, req: AssistantApplyReq):
    mdir = _mdir(slug)
    minutes = _minutes_file(mdir)
    if minutes is None:
        raise HTTPException(400, "没有可恢复的纪要")
    try:
        result = assistant.undo_minutes_edit(minutes, req.proposal_id)
        _refresh_evidence(mdir)
        return result
    except assistant.AssistantError as exc:
        _assistant_http_error(exc)
