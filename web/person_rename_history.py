"""Recoverable, cross-meeting snapshots for canonical person display renames."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = "person-display-rename/v1"
MAX_HISTORY = 20


def _digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _copy(source: Path, target: Path) -> None:
    if not source.is_file():
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    shutil.copy2(source, temporary)
    temporary.replace(target)


def _write(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _revisions(bank_dir: Path, meetings_root: Path, slugs: list[str]) -> dict:
    meetings = {}
    for slug in slugs:
        mdir = meetings_root / slug
        meetings[slug] = {
            "json": _digest(mdir / "transcript.spk.json"),
            "markdown": _digest(mdir / "transcript.spk.md"),
        }
    return {"bank": _digest(bank_dir / "bank.json"), "meetings": meetings}


def begin(bank_dir: Path, meetings_root: Path, person_id: str, slugs: list[str]) -> Path:
    root = bank_dir / ".history" / "person-renames"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    op_dir = root / f"{stamp}-{uuid.uuid4().hex[:8]}"
    before = op_dir / "before"
    before.mkdir(parents=True, exist_ok=False)
    _copy(bank_dir / "bank.json", before / "bank.json")
    for slug in slugs:
        mdir = meetings_root / slug
        _copy(mdir / "transcript.spk.json", before / slug / "transcript.spk.json")
        _copy(mdir / "transcript.spk.md", before / slug / "transcript.spk.md")
    _write(op_dir / "manifest.json", {
        "schema": SCHEMA,
        "state": "pending",
        "person_id": person_id,
        "slugs": slugs,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "before": _revisions(bank_dir, meetings_root, slugs),
    })
    return op_dir


def complete(op_dir: Path, bank_dir: Path, meetings_root: Path) -> None:
    path = op_dir / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["state"] = "complete"
    manifest["after"] = _revisions(bank_dir, meetings_root, manifest["slugs"])
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    _write(path, manifest)
    completed = sorted((row for row in op_dir.parent.iterdir() if row.is_dir()), reverse=True)
    for old in completed[MAX_HISTORY:]:
        shutil.rmtree(old, ignore_errors=True)


def rollback(op_dir: Path, bank_dir: Path, meetings_root: Path, *, require_current: bool) -> dict:
    path = op_dir / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        raise ValueError("Unsupported person rename history")
    if require_current and _revisions(bank_dir, meetings_root, manifest["slugs"]) != manifest.get("after"):
        raise ValueError("A newer identity change exists; undo the latest change first")
    before = op_dir / "before"
    _copy(before / "bank.json", bank_dir / "bank.json")
    for slug in manifest["slugs"]:
        target = meetings_root / slug
        _copy(before / slug / "transcript.spk.json", target / "transcript.spk.json")
        _copy(before / slug / "transcript.spk.md", target / "transcript.spk.md")
    manifest["state"] = "undone" if require_current else "rolled_back"
    manifest["restored_at"] = datetime.now(timezone.utc).isoformat()
    _write(path, manifest)
    return manifest


def latest(bank_dir: Path, meetings_root: Path, person_id: str | None = None):
    root = bank_dir / ".history" / "person-renames"
    if not root.is_dir():
        return None
    for op_dir in sorted((row for row in root.iterdir() if row.is_dir()), reverse=True):
        try:
            manifest = json.loads((op_dir / "manifest.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        if (manifest.get("schema") == SCHEMA and manifest.get("state") == "complete"
                and (person_id is None or manifest.get("person_id") == person_id)
                and _revisions(bank_dir, meetings_root, manifest["slugs"]) == manifest.get("after")):
            return op_dir, manifest
    return None
