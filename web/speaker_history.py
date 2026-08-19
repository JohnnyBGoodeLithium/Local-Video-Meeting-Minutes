"""可恢复的说话人/声纹事务快照。

快照只保存在对应会议的私有 ``.history/speakers`` 目录；不进入 Git，也不暴露
逐字稿或人员正文。撤销前校验当前 bank/transcript 仍等于该操作的 after revision，
避免覆盖随后发生的人工修改。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = "speaker-operation/v1"
MAX_HISTORY = 20


def _digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _write_json(path: Path, value: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _copy_file(source: Path, target: Path) -> None:
    if not source.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    shutil.copy2(source, tmp)
    tmp.replace(target)


def _emb_names(bank_dir: Path) -> list[str]:
    emb = bank_dir / "emb"
    return sorted(path.name for path in emb.glob("*.npy") if path.is_file())


def _emb_revisions(bank_dir: Path) -> dict[str, str | None]:
    return {name: _digest(bank_dir / "emb" / name) for name in _emb_names(bank_dir)}


def _revisions(mdir: Path, bank_dir: Path) -> dict:
    return {
        "bank": _digest(bank_dir / "bank.json"),
        "transcript_json": _digest(mdir / "transcript.spk.json"),
        "transcript_md": _digest(mdir / "transcript.spk.md"),
        "corrections": _digest(mdir / "speaker.corrections.json"),
        "embeddings": _emb_revisions(bank_dir),
    }


def begin(mdir: Path, bank_dir: Path, operation: str) -> Path:
    root = mdir / ".history" / "speakers"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    op_dir = root / f"{stamp}-{uuid.uuid4().hex[:8]}"
    before = op_dir / "before"
    before.mkdir(parents=True, exist_ok=False)
    _copy_file(bank_dir / "bank.json", before / "bank.json")
    _copy_file(mdir / "transcript.spk.json", before / "transcript.spk.json")
    _copy_file(mdir / "transcript.spk.md", before / "transcript.spk.md")
    _copy_file(mdir / "speaker.corrections.json", before / "speaker.corrections.json")
    for name in _emb_names(bank_dir):
        _copy_file(bank_dir / "emb" / name, before / "emb" / name)
    manifest = {
        "schema": SCHEMA,
        "operation": operation,
        "state": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "before": _revisions(mdir, bank_dir),
    }
    _write_json(op_dir / "manifest.json", manifest)
    return op_dir


def complete(op_dir: Path, mdir: Path, bank_dir: Path) -> None:
    manifest_path = op_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["state"] = "complete"
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    manifest["after"] = _revisions(mdir, bank_dir)
    _write_json(manifest_path, manifest)
    root = op_dir.parent
    completed = []
    for candidate in sorted(root.iterdir(), reverse=True):
        try:
            data = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("state") in {"complete", "undone"}:
            completed.append(candidate)
    for old in completed[MAX_HISTORY:]:
        shutil.rmtree(old, ignore_errors=True)


def _manifest(op_dir: Path) -> dict:
    data = json.loads((op_dir / "manifest.json").read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError("不支持的说话人历史版本")
    return data


def _matches_current(manifest: dict, mdir: Path, bank_dir: Path) -> bool:
    after = manifest.get("after") or {}
    current = _revisions(mdir, bank_dir)
    return all(current.get(key) == after.get(key)
               for key in ("bank", "transcript_json", "transcript_md",
                           "corrections", "embeddings"))


def latest_available(mdir: Path, bank_dir: Path) -> tuple[Path, dict] | None:
    root = mdir / ".history" / "speakers"
    if not root.is_dir():
        return None
    for candidate in sorted((path for path in root.iterdir() if path.is_dir()), reverse=True):
        try:
            manifest = _manifest(candidate)
        except Exception:
            continue
        if manifest.get("state") == "complete" and _matches_current(manifest, mdir, bank_dir):
            return candidate, manifest
    return None


def restore(op_dir: Path, mdir: Path, bank_dir: Path, *, require_current: bool) -> dict:
    manifest = _manifest(op_dir)
    if require_current and not _matches_current(manifest, mdir, bank_dir):
        raise ValueError("此操作之后已有新的说话人修改，不能覆盖；请撤销最新一项")
    before = op_dir / "before"
    _copy_file(before / "bank.json", bank_dir / "bank.json")
    _copy_file(before / "transcript.spk.json", mdir / "transcript.spk.json")
    _copy_file(before / "transcript.spk.md", mdir / "transcript.spk.md")
    corrections = before / "speaker.corrections.json"
    if corrections.is_file():
        _copy_file(corrections, mdir / "speaker.corrections.json")
    else:
        (mdir / "speaker.corrections.json").unlink(missing_ok=True)
    before_embeddings = manifest.get("before", {}).get("embeddings") or {}
    after_embeddings = manifest.get("after", {}).get("embeddings") or {}
    # 兼容早期开发快照的文件名列表。
    before_names = set(before_embeddings if isinstance(before_embeddings, list)
                       else before_embeddings.keys())
    after_names = set(after_embeddings if isinstance(after_embeddings, list)
                      else after_embeddings.keys()) or set(_emb_names(bank_dir))
    emb_dir = bank_dir / "emb"
    emb_dir.mkdir(parents=True, exist_ok=True)
    for name in after_names - before_names:
        (emb_dir / name).unlink(missing_ok=True)
    for name in before_names:
        _copy_file(before / "emb" / name, emb_dir / name)
    manifest["state"] = "undone" if require_current else "rolled_back"
    manifest["restored_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(op_dir / "manifest.json", manifest)
    return manifest


def discard_failed(op_dir: Path, mdir: Path, bank_dir: Path) -> None:
    restore(op_dir, mdir, bank_dir, require_current=False)


@contextmanager
def transaction(mdir: Path, bank_dir: Path, operation: str):
    op_dir = begin(mdir, bank_dir, operation)
    try:
        yield op_dir
    except Exception:
        discard_failed(op_dir, mdir, bank_dir)
        raise
    else:
        complete(op_dir, mdir, bank_dir)
