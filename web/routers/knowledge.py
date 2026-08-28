"""会议/媒体知识投影预检与一键发布。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import kb_document
from deps import BANK_DIR, _content_type, _meeting_identity, _mdir, _minutes_file, _read_json
from meeting_core import photos as meeting_photos
from meeting_core.knowledge_sink import (
    KnowledgeArtifact, KnowledgeSinkError, artifact_revision, configured_sink,
    configured_targets, publication_for, publish,
)
from meeting_core.source_info import load_source_info


router = APIRouter()


class PublishRequest(BaseModel):
    target_id: str
    profile: str = "auto"


def _content_type_for(mdir: Path) -> str:
    meta = _read_json(mdir / "meta.json", {})
    return _content_type(meta.get("content_type"))


def _visual_counts(mdir: Path) -> tuple[int, int]:
    pages = sum(1 for page in _read_json(mdir / "slides.json", [])
                if page.get("kind", "slide") == "slide")
    photos = len(meeting_photos.load(mdir).get("photos", []))
    return pages, photos


def _recommendation(mdir: Path, content_type: str) -> tuple[str, str]:
    pages, photos = _visual_counts(mdir)
    if content_type == "media" and pages:
        return "kb-html", "媒体视频的关键画面属于叙事来源，默认发布图文版"
    if content_type == "meeting" and photos:
        return "kb-html", "会议包含现场照片，图文版可保留白板或纸面资料"
    if content_type == "media":
        return "kb", "当前媒体没有可导出的关键画面，发布轻量文字版"
    return "kb", "会议默认以结论、待办、脉络、逐字稿和时间依据为主"


def _target_payload(mdir: Path, target, content_type: str) -> dict:
    record = publication_for(mdir, "weknora", target.id)
    return {
        "id": target.id, "name": target.name,
        "content_types": list(target.content_types),
        "available": content_type in target.content_types,
        "publication": ({key: record.get(key) for key in (
            "profile", "status", "parse_status", "published_at", "artifact_revision")}
                        if record else None),
    }


@router.get("/api/knowledge/targets")
def knowledge_targets():
    targets = configured_targets()
    provider = os.environ.get("MEETING_KB_PROVIDER", "weknora").strip().lower()
    api_ready = bool(os.environ.get("MEETING_KB_API_KEY", "").strip()
                     and (os.environ.get("MEETING_KB_API_URL", "").strip()
                          or os.environ.get("MEETING_KB_HEALTH_URL", "").strip()))
    return {
        "provider": provider, "configured": bool(targets and api_ready),
        "targets": [{"id": target.id, "name": target.name,
                     "content_types": list(target.content_types)} for target in targets],
        "setup_required": not bool(targets and api_ready),
    }


@router.get("/api/meetings/{slug}/knowledge/preflight")
def knowledge_preflight(slug: str):
    mdir = _mdir(slug)
    content_type = _content_type_for(mdir)
    recommended, reason = _recommendation(mdir, content_type)
    pages, photos = _visual_counts(mdir)
    targets = configured_targets()
    api_ready = bool(os.environ.get("MEETING_KB_API_KEY", "").strip())
    return {
        "provider": os.environ.get("MEETING_KB_PROVIDER", "weknora").strip().lower(),
        "configured": bool(targets and api_ready),
        "content_type": content_type, "document_ready": _minutes_file(mdir) is not None,
        "recommended_profile": recommended, "recommendation_reason": reason,
        "content": {"pages": pages, "photos": photos,
                    "transcript_turns": len(_read_json(mdir / "transcript.spk.json", []))},
        "targets": [_target_payload(mdir, target, content_type) for target in targets],
    }


def _artifact(mdir: Path, profile: str, content_type: str) -> KnowledgeArtifact:
    ident = _meeting_identity(mdir.name)
    date = str(ident.get("date") or "").strip()
    title = str(ident.get("title") or mdir.name).strip()
    source = load_source_info(mdir)
    platform = str(source.get("platform") or source.get("provider") or "").strip()
    prefix = "Meeting" if content_type == "meeting" else "Media"
    display_title = " · ".join(part for part in (
        prefix, platform if content_type == "media" else date, title) if part)
    base_url = kb_document.default_base_url()
    if profile == "kb-html":
        text, _stats = kb_document.kb_html_document(
            mdir, base_url=base_url, bank_dir=BANK_DIR,
            title=display_title, date=date)
        body = text.encode("utf-8")
        revision = artifact_revision(body)
        safe = kb_document._safe_name(display_title) or content_type
        filename = f"{safe}_{revision}.kb.html"
        return KnowledgeArtifact(display_title, profile, content_type, revision,
                                 filename, "text/html; charset=utf-8", body)
    text = kb_document.kb_document(
        mdir, base_url=base_url, bank_dir=BANK_DIR,
        title=display_title, date=date)
    body = text.encode("utf-8")
    revision = artifact_revision(body)
    return KnowledgeArtifact(display_title, "kb", content_type, revision,
                             f"{content_type}_{revision}.kb.md",
                             "text/markdown; charset=utf-8", body)


@router.post("/api/meetings/{slug}/knowledge/publish")
def publish_knowledge(slug: str, request: PublishRequest):
    mdir = _mdir(slug)
    if _minutes_file(mdir) is None:
        raise HTTPException(409, "纪要尚未就绪；逐字稿核听包可以导出，但不发布到正式知识库")
    content_type = _content_type_for(mdir)
    targets = configured_targets()
    target = next((item for item in targets if item.id == request.target_id), None)
    if target is None or content_type not in target.content_types:
        raise HTTPException(400, "知识库目标不存在或不接受当前内容类型")
    recommended, _reason = _recommendation(mdir, content_type)
    profile = recommended if request.profile == "auto" else request.profile
    if profile not in {"kb", "kb-html"}:
        raise HTTPException(400, "知识库发布格式无效")
    try:
        artifact = _artifact(mdir, profile, content_type)
        result = publish(mdir, target, artifact, configured_sink())
    except KnowledgeSinkError as exc:
        raise HTTPException(502, str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "provider": "weknora", "target": target.name,
            "profile": profile, "publication": result}
