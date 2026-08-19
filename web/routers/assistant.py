"""本地会议助手：问答、RAG 检索与纪要编辑提案。
服务 schema：meeting-rag/evidence-hybrid-v1、meeting-minutes-evidence/v1、
meeting-generation/v1。"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import json

import meeting_generation
from deps import (DRY_RUN, MD, artifact, assistant, _minutes_file, _mdir,
                  _read_json, _refresh_evidence)

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


class AssistantRestructureReq(BaseModel):
    message: str
    transcript_revision: str | None = None
    minutes_revision: str | None = None


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


def _reading_proposal(mdir, proposal: dict, *, restructure: bool = False) -> dict:
    """给修改卡补充安全、可读的 HTML；原始 marker 只留在写入协议里。

    整篇重组可引用已从当前阅读版省略的事实，所以 after 使用独立事实库存；
    before 仍使用当前 evidence。Markdown renderer 禁用原始 HTML，模型不能注入脚本。
    """
    current = _read_json(mdir / "minutes.evidence.json", {})
    inventory = _read_json(mdir / "meeting.facts.json", {}) if restructure else current
    after_source = artifact.normalize_minutes_markdown(str(proposal.get("after") or ""))
    before_source = artifact.normalize_minutes_markdown(str(proposal.get("before") or ""))
    proposal["after_html"] = MD.render(artifact.markdown_with_evidence_links(
        after_source, inventory if inventory.get("claims") else current))
    proposal["before_html"] = MD.render(artifact.markdown_with_evidence_links(
        before_source, current))
    return proposal


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


@router.post("/api/meetings/{slug}/assistant/chat/stream")
def assistant_chat_stream(slug: str, req: AssistantChatReq):
    """SSE 流式问答：meta(证据/检索元数据) → delta* → done。
    校验与检索在流开始前同步完成，冲突/错误仍走普通 HTTP 状态码。"""
    mdir = _mdir(slug)
    if not (mdir / "transcript.spk.json").is_file():
        raise HTTPException(400, "没有逐字稿，无法进行会议问答")
    try:
        prepared = assistant.prepare_answer(
            mdir, _assistant_message(req.message), req.turn_indexes,
            req.transcript_revision)
    except assistant.AssistantError as exc:
        _assistant_http_error(exc)

    def events():
        meta = {"type": "meta", "sources": prepared["sources"],
                "transcript_revision": prepared["revision"],
                "retrieval": prepared["retrieval"]}
        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"
        full = []
        try:
            for delta in assistant.stream_answer(prepared, req.message, req.history, DRY_RUN):
                full.append(delta)
                yield f"data: {json.dumps({'type': 'delta', 'text': delta}, ensure_ascii=False)}\n\n"
            done = {"type": "done", "answer": "".join(full)}
            yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"
        except assistant.AssistantError as exc:
            err = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store"})


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
        proposal = assistant.preview_minutes_edit(
            minutes, transcript, _assistant_message(req.message), req.turn_indexes,
            req.transcript_revision, req.minutes_revision, req.target_heading, DRY_RUN)
        return _reading_proposal(mdir, proposal)
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


@router.post("/api/meetings/{slug}/assistant/restructure/preview")
def assistant_restructure_preview(slug: str, req: AssistantRestructureReq):
    """按自然语言结构要求重组整篇纪要；Topic Map 始终保持时间线性。"""
    mdir = _mdir(slug)
    if meeting_generation.document_state(mdir, _minutes_file(mdir) is not None) == "draft":
        raise HTTPException(409, "语音草稿正在补充屏幕资料；终稿完成后才能重组纪要")
    transcript = mdir / "transcript.spk.json"
    minutes = _minutes_file(mdir)
    evidence = mdir / "minutes.evidence.json"
    if not transcript.is_file() or minutes is None or not evidence.is_file():
        raise HTTPException(400, "需要逐字稿、纪要和事实依据才能重组")
    try:
        proposal = assistant.preview_minutes_restructure(
            minutes, transcript, evidence, _assistant_message(req.message),
            req.transcript_revision, req.minutes_revision, DRY_RUN)
        return _reading_proposal(mdir, proposal, restructure=True)
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
