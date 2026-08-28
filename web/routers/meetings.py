"""会议列表、bundle、删除、存储与重生成。
服务 schema：meeting-structure/v2、meeting-topic-map/v3（兼容 v1/v2 旧图）、meeting-generation/v1、
meeting-minutes-evidence/v1、meeting-storage/v1。"""

import json
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query

import meeting_generation
import meeting_structure
import meeting_topic_map
import keyword_service
import minutes_view_service
import transcript_service
import voice_bank as vb
from meeting_core import photos as meeting_photos
from deps import (BANK_DIR, BANK_LOCK, CONTENT_TYPES, DRY_RUN, EVALUATIONS_DIR, MEETINGS, MD,
                  MEETING_META_LOCK, STORAGE_LOCK, artifact, assistant, _audio_path,
                  _clean_meeting_cache, _current_evidence, _evidence_state,
                  _meeting_identity, _meeting_storage, _mdir, _minutes_file, _now,
                  _minutes_html, _read_json, _source, _video_path)
from job_store import EXEC, JOBS, _new_job, _run_pipeline
from job_recovery import (build_minutes_command, build_retranscribe_command,
                          build_topic_map_command)

router = APIRouter()


_DERIVED_TIME_FILES = (
    "transcript.spk.json", "stamps.json", "diarization.json", "minutes.md",
    "minutes.spk.md", "minutes.evidence.json", "meeting.facts.json", "slides.json", "page_desc.json",
    "meeting.topic-map.json", "meeting.generation.json",
)


def _legacy_meeting_times(mdir: Path, meta: dict) -> tuple[float, float, bool]:
    """给旧会议提供保守的时间回退。

    优先用历史 upload job；再用派生文件时间。不读源媒体 mtime，
    因为它会在固化时保留来源设备的原始时间。
    """
    imported = float(meta.get("imported_at") or 0)
    estimated = not bool(imported)
    if not imported:
        uploads = [float(job.get("created") or 0) for job in JOBS.values()
                   if job.get("kind") == "upload" and job.get("meeting") == mdir.name
                   and job.get("status") == "done" and job.get("created")]
        if uploads:
            imported = min(uploads)
            estimated = False
    mtimes = [path.stat().st_mtime for name in _DERIVED_TIME_FILES
              if (path := mdir / name).is_file()]
    if not imported:
        imported = min(mtimes) if mtimes else mdir.stat().st_mtime
    updated = float(meta.get("updated_at") or 0)
    if not updated:
        updated = max(mtimes) if mtimes else imported
    return imported, updated, estimated


@router.get("/api/meetings")
def list_meetings():
    out = []
    if MEETINGS.is_dir():
        for d in MEETINGS.iterdir():
            if not d.is_dir():
                continue
            meta = _read_json(d / "meta.json", {})
            if not isinstance(meta, dict):
                meta = {}
            imported_at, updated_at, imported_at_estimated = _legacy_meeting_times(d, meta)
            item = {"slug": d.name, "has_transcript": False, "has_minutes": False,
                    "has_video": False, "turns": 0, "pages": 0, "duration": None,
                    "speaker_count": 0, "imported_at": imported_at,
                    "updated_at": updated_at,
                    "imported_at_estimated": imported_at_estimated,
                    **_meeting_identity(d.name)}
            turns = _read_json(d / "transcript.spk.json", [])
            if turns:
                item["has_transcript"] = True
                item["turns"] = len(turns)
                item["duration"] = max((t.get("end", 0) for t in turns), default=0)
                item["speaker_count"] = len({t.get("speaker") for t in turns if t.get("speaker")})
            slides = _read_json(d / "slides.json", [])
            item["pages"] = sum(1 for p in slides if p.get("kind") == "slide") or len(slides)
            item["has_minutes"] = _minutes_file(d) is not None
            item["has_video"] = _video_path(d) is not None
            item["generation_phase"] = meeting_generation.load(d).get("phase") or (
                "ready" if item["has_minutes"] else "processing")
            if item["has_minutes"]:
                kw_payload = keyword_service.keywords_payload(d)
                if kw_payload.get("state") == "ready":
                    item["keywords"] = [str(k.get("text") or "") for k in
                                        kw_payload.get("keywords", []) if k.get("text")]
            out.append(item)
    out.sort(key=lambda item: (item.get("imported_at") or 0, item["slug"]), reverse=True)
    return {"meetings": out}


@router.post("/api/meetings/{slug}/rename")
def rename_meeting(slug: str, title: str = Body(..., embed=True)):
    """网页端改名：写入 meta.json 的 title 字段（原子替换），不改目录名。
    注意：title 参与翻译上下文 revision，改名后已有译文会被标记为过期。"""
    mdir = _mdir(slug)
    title = title.strip()
    if not 1 <= len(title) <= 80:
        raise HTTPException(400, "标题需为 1–80 个字符")
    meta_path = mdir / "meta.json"
    with MEETING_META_LOCK:
        meta = _read_json(meta_path, {})
        if not isinstance(meta, dict):
            meta = {}
        meta["title"] = title
        meta["title_origin"] = "manual"
        meta["updated_at"] = _now()
        tmp = meta_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, meta_path)
    return {"ok": True, **_meeting_identity(slug)}


@router.post("/api/meetings/{slug}/content-type")
def set_content_type(slug: str, content_type: str = Body(..., embed=True)):
    """重新分类：会议 ↔ 媒体视频。只改 meta.json 的 content_type，
    逐字稿、纪要、索引和导出资产都不动。"""
    mdir = _mdir(slug)
    content_type = content_type.strip()
    if content_type not in CONTENT_TYPES:
        raise HTTPException(400, "content_type 只支持 meeting 或 media")
    meta_path = mdir / "meta.json"
    with MEETING_META_LOCK:
        meta = _read_json(meta_path, {})
        if not isinstance(meta, dict):
            meta = {}
        meta["content_type"] = content_type
        meta["updated_at"] = _now()
        tmp = meta_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, meta_path)
    return {"ok": True, **_meeting_identity(slug)}


@router.post("/api/meetings/{slug}/delete")
def delete_meeting(slug: str):
    """删除整个会议目录, 并清掉声纹库 sources 里对它的引用。"""
    mdir = _mdir(slug)
    shutil.rmtree(mdir)
    evaluation_removed = False
    evaluation_path = EVALUATIONS_DIR / f"{slug}.json"
    if evaluation_path.is_file():
        evaluation_path.unlink()
        evaluation_removed = True
    removed = 0
    with BANK_LOCK:
        bank = vb.load_bank(BANK_DIR)
        for v in bank["voices"]:
            if vb.forget_source(v, slug):
                removed += 1
        if removed:
            vb.save_bank(BANK_DIR, bank)
    return {"ok": True, "bank_refs_removed": removed,
            "evaluation_removed": evaluation_removed}


@router.get("/api/meetings/{slug}/storage")
def meeting_storage(slug: str):
    """查看会议逻辑占用；原始母版、阅读资产和可再生缓存严格分开。"""
    with STORAGE_LOCK:
        return _meeting_storage(_mdir(slug))


@router.post("/api/meetings/{slug}/storage/cleanup")
def clean_meeting_storage(slug: str):
    """只删除白名单内可再生缓存；永不删除母版、逐字稿、纪要或阅读页面。"""
    if any(job.get("meeting") == slug and job.get("status") in {"queued", "running"}
           for job in JOBS.values()):
        raise HTTPException(409, "会议仍在处理，完成后才能清理缓存")
    with STORAGE_LOCK:
        return _clean_meeting_cache(_mdir(slug))


@router.get("/api/meetings/{slug}/bundle")
def get_bundle(slug: str):
    mdir = _mdir(slug)
    transcript = _read_json(mdir / "transcript.spk.json", [])
    slides = _read_json(mdir / "slides.json", [])
    minutes_html, topics = _minutes_html(mdir, slug)
    src = _source(mdir)
    samples_dir = mdir / "samples"
    samples = sorted(p.stem for p in samples_dir.glob("*.wav")) if samples_dir.is_dir() else []
    evidence = _current_evidence(mdir)
    duration = max((turn.get("end", 0) for turn in transcript), default=0)
    raw_desc = _read_json(mdir / "page_desc.json", {}).get("desc", {})
    descriptions = {int(key): str(value) for key, value in raw_desc.items()
                    if str(key).isdigit()}
    minutes_path = _minutes_file(mdir)
    structure = meeting_structure.build_structure(
        minutes_path.read_text(encoding="utf-8") if minutes_path else "",
        transcript, slides, descriptions, evidence, duration=duration)
    photo_visuals = meeting_photos.project(mdir)
    structure["visuals"] = sorted(
        [*(structure.get("visuals") or []), *photo_visuals],
        key=lambda visual: (
            visual.get("first") is None,
            float(visual.get("first") or 0) if visual.get("first") is not None else 10**12,
            str(visual.get("id") or "")),
    )
    # VL 结果本身通常是 Markdown；沿用纪要的安全渲染配置（禁用原始 HTML），
    # 让屏幕内容页保持可读层级，而不是把标题/列表作为原始文本展示。
    for visual in structure.get("visuals", []):
        visual["description_html"] = MD.render(
            visual.get("display_description") or "当前画面没有可用的 VL 详细解读。")
    topic_state, topic_map = meeting_topic_map.load_current_topic_map(mdir)
    topic_payload = ({**topic_map, "state": "ready"} if topic_state == "ready" else
                     {"schema": meeting_topic_map.SCHEMA, "state": topic_state, "topics": []})
    generation = meeting_generation.load(mdir)
    if not generation:
        generation = {"schema": meeting_generation.SCHEMA,
                      "phase": "ready" if minutes_html else "processing", "inferred": True}
    document_state = meeting_generation.document_state(
        mdir, bool(transcript and minutes_html))
    if document_state == "ready" and not DRY_RUN and not any(
            job.get("meeting") == slug and job.get("status") in {"queued", "running"}
            for job in JOBS.values()):
        # 旧会议在首次阅读时惰性补翻与补关键字；异常不能影响 bundle 阅读。
        try:
            from routers.translations import auto_translate_after_ready
            auto_translate_after_ready(slug, mdir)
        except Exception:
            pass
        try:
            from routers.keywords import auto_keywords_after_ready
            auto_keywords_after_ready(slug, mdir)
        except Exception:
            pass
    actions = artifact.action_items_from_claims(evidence.get("claims", []))
    action_candidates = evidence.get("action_candidates")
    if action_candidates is None and minutes_path:
        action_candidates = artifact.action_candidates_from_minutes(
            minutes_path.read_text(encoding="utf-8"), actions)
    transcript_source = str(src.get("transcript_source") or "").lower()
    if transcript_source not in {"external", "local_asr"}:
        transcript_source = ("external" if src.get("transcript_format")
                             or any((mdir / f"source.{suffix}").is_file()
                                    for suffix in ("vtt", "docx")) else "local_asr")
    transcript_format = str(src.get("transcript_format") or "").lower() \
        if transcript_source == "external" else ""
    if transcript_source == "external" and not transcript_format:
        transcript_format = next((suffix for suffix in ("vtt", "docx")
                                  if (mdir / f"source.{suffix}").is_file()), "")
    profiles = evidence.get("speaker_profiles") or artifact.load_speaker_profiles(
        transcript, BANK_DIR)
    minutes_revision = assistant.revision(minutes_path) if minutes_path else None
    minutes_history = mdir / ".history" / "minutes"
    minutes_history_available = bool(minutes_path and minutes_history.is_dir() and any(
        path.is_file() and path.read_bytes() != minutes_path.read_bytes()
        for path in minutes_history.glob("*.md")))
    fact_inventory = _read_json(mdir / "meeting.facts.json", {})
    minutes_views = []
    for view in minutes_view_service.list_views(mdir, minutes_revision):
        reading = artifact.minutes_reading_markdown(
            view.get("markdown") or "", fact_inventory, include_topic_section=False)
        reading = artifact.markdown_with_evidence_links(reading, fact_inventory)
        minutes_views.append({
            "id": view.get("id"),
            "title": view.get("title") or "AI 重组纪要",
            "summary": view.get("summary") or "",
            "created_at": view.get("created_at"),
            "html": MD.render(reading),
            "sources": view.get("sources") or [],
        })
    return {
        "slug": slug,
        **_meeting_identity(slug),
        "transcript": transcript,
        "slides": slides,
        "minutes_html": minutes_html,
        "has_minutes": bool(minutes_html),
        "topics": topics,
        "samples": samples,
        "source": {k: bool(v) for k, v in src.items()},  # 不把原始路径暴露给前端逻辑判断以外
        "transcript_source": transcript_source,
        "external_transcript_available": any(
            (mdir / f"source.{suffix}").is_file() for suffix in ("vtt", "docx")),
        "has_audio": _audio_path(mdir) is not None,
        "has_video": _video_path(mdir) is not None,
        "duration": duration,
        "speaker_count": len({t.get("speaker") for t in transcript if t.get("speaker")}),
        "speaker_navigation": artifact.speaker_navigation(
            transcript, profiles, transcript_format),
        "transcript_revision": assistant.revision(mdir / "transcript.spk.json"),
        "transcript_review": transcript_service.project_review(mdir, bool(evidence)),
        "keywords": keyword_service.keywords_payload(mdir),
        "minutes_revision": minutes_revision,
        "minutes_views": minutes_views,
        "minutes_history_available": minutes_history_available,
        "document_state": document_state,
        "generation": generation,
        "structure": structure,
        "photos": photo_visuals,
        "topic_map": topic_payload,
        "evidence": {
            "schema": evidence.get("schema"),
            "state": _evidence_state(mdir, evidence),
            "claims": evidence.get("claims", []),
            "actions": actions,
            "action_candidates": action_candidates or [],
            "linkage": evidence.get("linkage", {}),
        },
    }


@router.post("/api/meetings/{slug}/retranscribe-local")
def retranscribe_local(slug: str):
    """保留母版与旧快照，使用当前显式配置的 ASR provider 重建。"""
    mdir = _mdir(slug)
    if any(job.get("meeting") == slug and job.get("status") in {"queued", "running"}
           for job in JOBS.values()):
        raise HTTPException(409, "这场会议仍有处理作业，不能并发重转写")
    if _video_path(mdir) is None and _audio_path(mdir) is None:
        raise HTTPException(400, "没有受保护的音视频母版，无法重新转写")
    cmd = build_retranscribe_command(mdir)
    job = _new_job("retranscribe", route="video", meeting=slug, cmd=cmd,
                   transcript_policy="local_asr")
    response = dict(job)
    EXEC.submit(_run_pipeline, job)
    return response


@router.post("/api/meetings/{slug}/regen_minutes")
def regen_minutes(slug: str, refine: str = Query("")):
    mdir = _mdir(slug)
    active = any(job.get("meeting") == slug and job.get("status") in {"queued", "running"}
                 for job in JOBS.values())
    if active:
        raise HTTPException(409, "这场会议仍有处理作业，不能并发重生成")
    generation = meeting_generation.load(mdir)
    if meeting_generation.document_state(mdir, _minutes_file(mdir) is not None) == "draft":
        # 服务或模型中断后允许复用已有 transcript/slides/VL cache 续跑视觉补充；
        # 正常运行时由上面的 active 检查阻止第二个 writer。
        resumable = (generation.get("phase") == "visual_enrichment"
                     and (mdir / "slides.json").is_file()
                     and (mdir / "transcript.spk.json").is_file())
        if not resumable:
            raise HTTPException(409, "语音草稿仍在补充屏幕资料，暂不能重新生成")
    if not (mdir / "transcript.spk.json").is_file():
        raise HTTPException(400, "没有逐字稿，无法重生成")
    try:
        cmd = build_minutes_command(mdir, refine)
    except ValueError as exc:
        messages = {
            "audio_refine_unsupported": "纯音频会议不支持优化全文(无分页资料)",
            "missing_visual_cache": "视频会议缺少可复用的屏幕缓存，请重新导入以恢复抽帧阶段",
        }
        raise HTTPException(400, messages.get(str(exc), "现有资产不足，无法重生成")) from exc
    job = _new_job("regen", meeting=slug, cmd=cmd)
    resp = dict(job)
    EXEC.submit(_run_pipeline, job)
    return resp


@router.post("/api/meetings/{slug}/topic-map")
def generate_topic_map(slug: str):
    """串行生成整场语义脉络；不修改逐字稿、纪要或屏幕资料。"""
    mdir = _mdir(slug)
    if meeting_generation.document_state(mdir, _minutes_file(mdir) is not None) == "draft":
        raise HTTPException(409, "语音草稿正在升级；多模态终稿后再生成会议脉络")
    if _minutes_file(mdir) is None or not (mdir / "transcript.spk.json").is_file():
        raise HTTPException(400, "会议缺少纪要或逐字稿，无法生成语义脉络")
    cmd = build_topic_map_command(mdir)
    job = _new_job("topic_map", meeting=slug, cmd=cmd)
    resp = dict(job)
    EXEC.submit(_run_pipeline, job)
    return resp
