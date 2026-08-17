"""会议列表、bundle、删除、存储与重生成。
服务 schema：meeting-structure/v2、meeting-topic-map/v3（兼容 v1/v2 旧图）、meeting-generation/v1、
meeting-minutes-evidence/v1、meeting-storage/v1。"""

import json
import os
import shutil

from fastapi import APIRouter, Body, HTTPException, Query

import meeting_generation
import meeting_structure
import meeting_topic_map
import voice_bank as vb
from deps import (BANK_DIR, BANK_LOCK, DRY_RUN, EVALUATIONS_DIR, MEETINGS, MD, PY, ROOT,
                  STORAGE_LOCK, artifact, assistant, _audio_path,
                  _clean_meeting_cache, _current_evidence, _evidence_state,
                  _meeting_identity, _meeting_storage, _mdir, _minutes_file,
                  _minutes_html, _read_json, _source, _video_path)
from job_store import EXEC, JOBS, _new_job, _run_pipeline

router = APIRouter()


@router.get("/api/meetings")
def list_meetings():
    out = []
    if MEETINGS.is_dir():
        for d in sorted(MEETINGS.iterdir(), key=lambda p: p.name, reverse=True):
            if not d.is_dir():
                continue
            item = {"slug": d.name, "has_transcript": False, "has_minutes": False,
                    "has_video": False, "turns": 0, "pages": 0, "duration": None,
                    "speaker_count": 0, **_meeting_identity(d.name)}
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
            out.append(item)
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
    meta = _read_json(meta_path, {})
    if not isinstance(meta, dict):
        meta = {}
    meta["title"] = title
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
            srcs = v.get("sources", [])
            if slug in srcs:
                srcs.remove(slug)
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
        # 旧会议在首次阅读时惰性补翻；异常不能影响 bundle 阅读。
        try:
            from routers.translations import auto_translate_after_ready
            auto_translate_after_ready(slug, mdir)
        except Exception:
            pass
    actions = artifact.action_items_from_claims(evidence.get("claims", []))
    action_candidates = evidence.get("action_candidates")
    if action_candidates is None and minutes_path:
        action_candidates = artifact.action_candidates_from_minutes(
            minutes_path.read_text(encoding="utf-8"), actions)
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
        "has_audio": _audio_path(mdir) is not None,
        "has_video": _video_path(mdir) is not None,
        "duration": duration,
        "speaker_count": len({t.get("speaker") for t in transcript if t.get("speaker")}),
        "transcript_revision": assistant.revision(mdir / "transcript.spk.json"),
        "minutes_revision": assistant.revision(_minutes_file(mdir)) if _minutes_file(mdir) else None,
        "document_state": document_state,
        "generation": generation,
        "structure": structure,
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
    if (mdir / "slides.json").is_file():
        cmd = [str(PY), str(ROOT / "bin" / "minutes_by_page.py"), str(mdir), "--publish"]
        video = _video_path(mdir)
        if video is not None:
            cmd += ["--video", str(video)]
        if refine:
            cmd += ["--refine-model", refine]
    else:
        # 纯音频会议(录音笔导入)没有分页资料, 走与 run_all 相同的整场纪要管线
        if refine:
            raise HTTPException(400, "纯音频会议不支持优化全文(无分页资料)")
        cmd = [str(PY), str(ROOT / "bin" / "summarize.py"), str(mdir / "transcript.txt"),
               "--spk", str(mdir / "transcript.spk.json"), "--max-tokens", "8192"]
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
    cmd = [str(PY), str(ROOT / "bin" / "meeting_topic_map.py"), str(mdir)]
    job = _new_job("topic_map", meeting=slug, cmd=cmd)
    resp = dict(job)
    EXEC.submit(_run_pipeline, job)
    return resp
