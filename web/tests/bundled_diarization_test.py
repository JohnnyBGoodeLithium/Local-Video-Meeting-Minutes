#!/usr/bin/env python3
"""Exercise the release model exception using synthetic bytes only."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from bundled_diarization import MANIFEST_PATH, MODEL_FILES, MODEL_ROOT, verified_model_files
from build_diarization_runtime_pack import ModelPackError
from build_release_bundle import forbidden_reason


def rejected(root):
    try:
        verified_model_files(root)
    except ModelPackError:
        return
    raise AssertionError("invalid bundled model accepted")


with tempfile.TemporaryDirectory(prefix="synthetic-bundled-model-") as tmp:
    root = Path(tmp)
    assert verified_model_files(root) == set()
    records = []
    for name in sorted(MODEL_FILES):
        relative = f"{MODEL_ROOT}/{name}"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = b"synthetic model fixture, not real weights\n"
        path.write_bytes(data)
        records.append({"path": relative, "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest()})
    metadata = {
        "schema": "bundled-diarization-model/v1",
        "upstream_id": "example/synthetic", "revision": "synthetic-1",
        "license": "Synthetic-Test-License", "attribution": "Synthetic fixture",
        "redistribution": {"allowed": True, "terms": "Synthetic test only",
                           "verified_by": "Synthetic test", "verified_at": "2030-01-01"},
        "submodels": [{"upstream_id": "example/synthetic-sub", "revision": "synthetic-1",
                       "license": "Synthetic-Test-License", "attribution": "Synthetic fixture",
                       "redistribution": {"allowed": True, "terms": "Synthetic test only"}}],
        "files": records,
    }
    manifest = root / MANIFEST_PATH
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(metadata))
    paths = verified_model_files(root)
    assert paths == {r["path"] for r in records}
    # The generic policy still rejects every model, including the known model.
    assert all(forbidden_reason(path) for path in paths)
    assert forbidden_reason("models/other/weights.bin")

    victim = root / records[0]["path"]
    original = victim.read_bytes()
    victim.write_bytes(b"modified")
    rejected(root)
    victim.unlink()
    rejected(root)
    victim.symlink_to(root / records[1]["path"])
    rejected(root)
    victim.unlink()
    victim.write_bytes(original)

    metadata["redistribution"]["allowed"] = False
    manifest.write_text(json.dumps(metadata))
    rejected(root)
    metadata["redistribution"]["allowed"] = True
    metadata["files"] = records + [dict(records[0])]
    manifest.write_text(json.dumps(metadata))
    rejected(root)
    metadata["files"] = records
    lfs = b"version https://git-lfs.github.com/spec/v1\n"
    victim.write_bytes(lfs)
    records[0].update(size=len(lfs), sha256=hashlib.sha256(lfs).hexdigest())
    manifest.write_text(json.dumps(metadata))
    rejected(root)

print("bundled diarization: synthetic hash, missing, symlink, license, duplicate and LFS checks passed")
