#!/usr/bin/env python3
"""会议渐进生成状态：先发布语音草稿，再用 VL 升级为多模态纪要。

状态文件只保存阶段、revision 和数量，不复制逐字稿或纪要正文。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import meeting_artifact as artifact


SCHEMA = "meeting-generation/v1"
VOICE_PHASES = {"voice_draft_generating", "voice_draft", "visual_enrichment"}


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
                   voice_draft_claims=claims)
    print(f"[meta] 语音草稿已可阅读 | 结论 {claims} 条 | 正在补充屏幕资料", flush=True)
    return state


def begin_visual_enrichment(mdir: Path) -> dict:
    return update(mdir, "visual_enrichment")


def finalize(mdir: Path, *, pages: int, vl_pages: int) -> dict:
    mdir = Path(mdir)
    draft_evidence = _read_json(mdir / "minutes.voice-draft.evidence.json", {})
    final_evidence = _read_json(mdir / "minutes.evidence.json", {})
    draft_claims = draft_evidence.get("claims", [])
    final_claims = final_evidence.get("claims", [])
    draft_text = {" ".join(str(item.get("text") or "").split()) for item in draft_claims}
    final_text = {" ".join(str(item.get("text") or "").split()) for item in final_claims}
    enrichment = {
        "pages": int(pages), "vl_pages": int(vl_pages),
        "draft_claims": len(draft_claims), "final_claims": len(final_claims),
        "added_claims": len(final_text - draft_text),
        "reframed_or_removed_claims": len(draft_text - final_text),
    }
    return update(
        mdir, "ready", final_revision=artifact.file_revision(mdir / "minutes.md"),
        enrichment=enrichment)


def document_state(mdir: Path, has_document: bool) -> str:
    if not has_document:
        return "processing"
    phase = load(mdir).get("phase")
    return "draft" if phase in VOICE_PHASES else "ready"
