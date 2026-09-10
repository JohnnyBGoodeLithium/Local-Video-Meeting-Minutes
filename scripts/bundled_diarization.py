"""The sole, hash-pinned model exception to application release boundaries."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from build_diarization_runtime_pack import ModelPackError, validate_redistribution

MODEL_ROOT = "models/pyannote/speaker-diarization-community-1"
MANIFEST_PATH = "release/diarization-model.json"
MODEL_FILES = {
    "config.yaml", "README.md", "THIRD_PARTY_NOTICES.md",
    "segmentation/pytorch_model.bin", "embedding/pytorch_model.bin",
    "embedding/README.md", "plda/README.md", "plda/plda.npz", "plda/xvec_transform.npz",
}


def verified_model_files(root: Path) -> set[str]:
    """Return exact permitted paths after validating provenance and all bytes.

    Older application releases without this manifest keep the no-model policy.
    This verifies files without importing torch, loading weights, or networking.
    """
    manifest_path = root / MANIFEST_PATH
    if not manifest_path.exists():
        return set()
    if manifest_path.is_symlink():
        raise ModelPackError("bundled model manifest must not be a symlink")
    metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
    if metadata.get("schema") != "bundled-diarization-model/v1":
        raise ModelPackError("unsupported bundled model manifest")
    validate_redistribution(metadata)
    records = metadata.get("files")
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise ModelPackError("bundled model records must be a list of objects")
    paths = [r.get("path") for r in records]
    expected = {f"{MODEL_ROOT}/{name}" for name in MODEL_FILES}
    if len(paths) != len(expected) or set(paths) != expected:
        raise ModelPackError("bundled model file set differs from the permitted model")
    for record in records:
        relative = record["path"]
        path = root / relative
        if any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
            raise ModelPackError(f"bundled model symlink: {relative}")
        if not path.is_file():
            raise ModelPackError(f"bundled model missing: {relative}")
        size = record.get("size")
        digest = record.get("sha256")
        if not isinstance(size, int) or not 0 < size <= 50 * 1024 * 1024:
            raise ModelPackError(f"invalid bundled model size: {relative}")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ModelPackError(f"invalid bundled model digest: {relative}")
        data = path.read_bytes()
        if data.startswith(b"version https://git-lfs.github.com/spec/"):
            raise ModelPackError(f"bundled model contains an LFS pointer: {relative}")
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise ModelPackError(f"bundled model checksum mismatch: {relative}")
    return expected
