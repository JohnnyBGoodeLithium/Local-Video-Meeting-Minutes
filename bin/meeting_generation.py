#!/usr/bin/env python3
"""会议渐进生成状态：先发布语音草稿，再用 VL 升级为多模态纪要。

状态文件只保存阶段、revision 和数量，不复制逐字稿或纪要正文。
"""

from __future__ import annotations

import json
from difflib import SequenceMatcher
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import meeting_artifact as artifact


SCHEMA = "meeting-generation/v1"
VOICE_PHASES = {"voice_draft_generating", "voice_draft", "visual_enrichment"}
MATERIAL_STATUSES = {"confirmed", "working_alignment", "proposal", "open"}
DETAIL_SECTIONS = ("分页详情", "逐页详情", "页面详情", "分镜头详情", "附录")


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load(mdir: Path) -> dict:
    value = _read_json(Path(mdir) / "meeting.generation.json", {})
    return value if value.get("schema") == SCHEMA else {}


def update(mdir: Path, phase: str, **values) -> dict:
    mdir = Path(mdir)
    path = mdir / "meeting.generation.json"
    current = load(mdir)
    value = {
        "schema": SCHEMA,
        "phase": phase,
        "created_at": current.get("created_at") or datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **{key: item for key, item in current.items()
           if key not in {"schema", "phase", "updated_at"}},
        **values,
    }
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(path)
    return value


def generate_voice_draft(mdir: Path, python: Path | str = sys.executable) -> bool:
    """调用现有文本纪要器发布 minutes.md；失败不阻断后续多模态终稿。"""
    mdir = Path(mdir)
    transcript = mdir / "transcript.spk.json"
    readable = mdir / "transcript.spk.md"
    update(mdir, "voice_draft_generating")
    command = [
        str(python), str(Path(__file__).with_name("summarize.py")), str(readable),
        "--spk", str(transcript), "--out", str(mdir), "--output-name", "minutes.md",
        "--max-tokens", "8192", "--generation-stage", "voice_draft", "--skip-topic-map",
    ]
    completed = subprocess.run(command)
    if completed.returncode:
        update(mdir, "voice_draft_failed", voice_draft_rc=completed.returncode)
        print(f"[error] 语音草稿生成失败 (rc={completed.returncode})，继续生成多模态纪要",
              flush=True)
        return False
    if not (mdir / "minutes.md").is_file():
        update(mdir, "voice_draft_failed", voice_draft_rc=-1)
        return False
    publish_voice_draft(mdir)
    return True


def publish_voice_draft(mdir: Path) -> dict:
    """将已生成的 canonical 纪要快照为可回溯语音草稿，并发布可读状态。"""
    mdir = Path(mdir)
    minutes = mdir / "minutes.md"
    evidence = mdir / "minutes.evidence.json"
    if not minutes.is_file():
        raise FileNotFoundError(minutes)
    shutil.copy2(minutes, mdir / "minutes.voice-draft.md")
    if evidence.is_file():
        shutil.copy2(evidence, mdir / "minutes.voice-draft.evidence.json")
    claims = len(_read_json(evidence, {}).get("claims", []))
    state = update(mdir, "voice_draft", voice_draft_revision=artifact.file_revision(minutes),
                   voice_draft_claims=claims, voice_draft_rc=None)
    print(f"[meta] 语音草稿已可阅读 | 结论 {claims} 条 | 正在补充屏幕资料", flush=True)
    return state


def begin_visual_enrichment(mdir: Path) -> dict:
    return update(mdir, "visual_enrichment")


def _material_claims(document: dict) -> list[dict]:
    """只审计语音草稿的决定、行动、方向和未决项，不拿逐页数量制造假覆盖率。"""
    result = []
    for claim in document.get("claims", []):
        section = str(claim.get("section") or "")
        if any(token in section for token in DETAIL_SECTIONS):
            continue
        kind = str(claim.get("kind") or "discussion")
        status = str(claim.get("status") or "informational")
        turns = [str(value) for value in claim.get("turn_ids", []) if str(value)]
        if not turns or kind == "slide_fact":
            continue
        if (claim.get("formal_action") or kind in {"decision", "action", "risk", "open_issue"}
                or status in MATERIAL_STATUSES):
            result.append(claim)
    return result


def voice_draft_checklist(mdir: Path, *, limit: int = 36) -> dict:
    """给终稿的低信任覆盖清单；最终仍须逐条回看原始 T 证据。"""
    claims = _material_claims(_read_json(
        Path(mdir) / "minutes.voice-draft.evidence.json", {}))

    def priority(claim):
        if claim.get("formal_action") or claim.get("kind") == "action":
            return 0
        if claim.get("kind") == "decision" and claim.get("status") == "confirmed":
            return 1
        if claim.get("status") == "open":
            return 2
        return 3

    items, chars = [], 0
    for claim in sorted(claims, key=priority):
        text = " ".join(str(claim.get("text") or "").split())[:320]
        if not text or chars + len(text) > 9000 or len(items) >= limit:
            continue
        item = {
            "draft_claim_id": str(claim.get("id") or ""),
            "kind": str(claim.get("kind") or "discussion"),
            "status": str(claim.get("status") or "informational"),
            "formal_action": bool(claim.get("formal_action")),
            "turn_ids": [str(value) for value in claim.get("turn_ids", []) if str(value)],
            "text": text,
        }
        items.append(item)
        chars += len(text)
    return {"schema": "meeting-voice-draft-checklist/v1", "items": items}


def _claim_compatible(draft: dict, final: dict) -> bool:
    if draft.get("formal_action") or draft.get("kind") == "action":
        return bool(final.get("formal_action") or final.get("kind") == "action")
    if draft.get("kind") == "decision":
        return final.get("kind") == "decision" or final.get("status") in {
            "confirmed", "working_alignment", "proposal"}
    if draft.get("status") == "open" or draft.get("kind") in {"risk", "open_issue"}:
        return final.get("status") == "open" or final.get("kind") in {"risk", "open_issue"}
    return final.get("status") != "informational" or final.get("kind") != "slide_fact"


def coverage_audit(draft_document: dict, final_document: dict) -> dict:
    """用证据重叠审计顶层语音事实是否在终稿中被保留/合并；不比较总字数。"""
    drafts = _material_claims(draft_document)
    finals = _material_claims(final_document)
    covered = []
    text_only_candidates = 0
    for draft in drafts:
        draft_turns = set(map(str, draft.get("turn_ids", [])))
        draft_text = " ".join(str(draft.get("text") or "").casefold().split())
        matched = False
        text_only = False
        for final in finals:
            if not _claim_compatible(draft, final):
                continue
            final_turns = set(map(str, final.get("turn_ids", [])))
            overlap = bool(draft_turns & final_turns)
            final_text = " ".join(str(final.get("text") or "").casefold().split())
            text_match = bool(draft_text and final_text and SequenceMatcher(
                None, draft_text, final_text).ratio() >= 0.72)
            if overlap:
                matched = True
                break
            if text_match:
                text_only = True
        if not matched and text_only:
            text_only_candidates += 1
        covered.append(matched)
    missing = sum(not value for value in covered)
    action_indexes = [index for index, claim in enumerate(drafts)
                      if claim.get("formal_action") or claim.get("kind") == "action"]
    missing_actions = sum(not covered[index] for index in action_indexes)
    total = len(drafts)
    return {
        "quality_state": "pass" if missing == 0 else "review_needed",
        "material_draft_claims": total,
        "covered_material_claims": total - missing,
        "unresolved_material_claims": missing,
        "material_coverage": round((total - missing) / total, 3) if total else 1.0,
        "draft_actions": len(action_indexes),
        "unresolved_actions": missing_actions,
        "text_only_candidates": text_only_candidates,
    }


def finalize(mdir: Path, *, pages: int, vl_pages: int,
             visual_mode: str | None = None) -> dict:
    mdir = Path(mdir)
    draft_evidence = _read_json(mdir / "minutes.voice-draft.evidence.json", {})
    final_evidence = _read_json(mdir / "minutes.evidence.json", {})
    draft_claims = draft_evidence.get("claims", [])
    final_claims = final_evidence.get("claims", [])
    draft_text = {" ".join(str(item.get("text") or "").split()) for item in draft_claims}
    final_text = {" ".join(str(item.get("text") or "").split()) for item in final_claims}
    resolved_visual_mode = visual_mode or ("complete" if vl_pages else "not_available")
    enrichment = {
        "pages": int(pages), "vl_pages": int(vl_pages),
        "visual_mode": resolved_visual_mode,
        "draft_claims": len(draft_claims), "final_claims": len(final_claims),
        "added_claims": len(final_text - draft_text),
        "reframed_or_removed_claims": len(draft_text - final_text),
        **coverage_audit(draft_evidence, final_evidence),
    }
    return update(
        mdir, "ready", final_revision=artifact.file_revision(mdir / "minutes.md"),
        result_mode=("voice_only" if resolved_visual_mode == "skipped_by_user"
                     else "multimodal"), enrichment=enrichment)


def document_state(mdir: Path, has_document: bool) -> str:
    if not has_document:
        return "processing"
    phase = load(mdir).get("phase")
    return "draft" if phase in VOICE_PHASES else "ready"
