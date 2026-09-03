#!/usr/bin/env python3
"""Diarization runtime packs require explicit redistribution evidence."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from build_diarization_runtime_pack import ModelPackError, build
from verify_diarization_runtime_pack import verify


def metadata(allowed=True):
    return {
        "upstream_id": "example/synthetic-diarization",
        "revision": "synthetic-rev-1",
        "license": "Synthetic-Test-License",
        "attribution": "Synthetic model fixture; not a real model.",
        "redistribution": {
            "allowed": allowed,
            "terms": "Synthetic test redistribution only.",
            "verified_by": "Automated synthetic fixture",
            "verified_at": "2030-01-01",
        },
        "submodels": [{
            "upstream_id": "example/synthetic-embedding",
            "revision": "synthetic-sub-rev-1",
            "license": "Synthetic-Test-License",
            "attribution": "Synthetic submodel fixture.",
            "redistribution": {"allowed": allowed, "terms": "Synthetic tests only."},
        }],
    }


with tempfile.TemporaryDirectory(prefix="mm-diarization-pack-") as tmp:
    root = Path(tmp)
    model = root / "model"
    model.mkdir()
    (model / "config.yaml").write_text("pipeline: synthetic\n", encoding="utf-8")
    (model / "weights.safetensors").write_bytes(b"synthetic-dummy-weights")
    meta = root / "metadata.json"
    meta.write_text(json.dumps(metadata()), encoding="utf-8")
    notices = root / "THIRD_PARTY_NOTICES.md"
    notices.write_text("# Synthetic notices\n\nNo real model is included.\n", encoding="utf-8")
    pack = build(model, meta, notices, root / "dist")
    result = verify(pack)
    assert result["files"] == 2
    assert result["revision"] == "synthetic-rev-1"
    assert pack.name == "diarization-runtime-community-1-synthetic-rev-1.zip"

    denied = root / "denied.json"
    denied.write_text(json.dumps(metadata(False)), encoding="utf-8")
    try:
        build(model, denied, notices, root / "denied-dist")
    except ModelPackError:
        pass
    else:
        raise AssertionError("unverified redistribution produced a pack")

    unknown = metadata()
    unknown["license"] = "unknown"
    unknown_path = root / "unknown.json"
    unknown_path.write_text(json.dumps(unknown), encoding="utf-8")
    try:
        build(model, unknown_path, notices, root / "unknown-dist")
    except ModelPackError:
        pass
    else:
        raise AssertionError("unknown license produced a pack")

    unsafe_model = root / "unsafe-model"
    unsafe_model.mkdir()
    (unsafe_model / "weights.safetensors").symlink_to(model / "weights.safetensors")
    try:
        build(unsafe_model, meta, notices, root / "unsafe-dist")
    except ModelPackError as exc:
        assert "unsafe model file" in str(exc)
    else:
        raise AssertionError("symlinked model weight produced a pack")

print("diarization pack tests: OK")
