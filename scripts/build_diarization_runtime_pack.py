#!/usr/bin/env python3
"""Build a separately distributed, license-gated diarization runtime pack."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile


MODEL_PACK_SCHEMA = "diarization-runtime-pack/v1"
MAX_FILE_BYTES = 4 * 1024 * 1024 * 1024
FORBIDDEN_NAMES = {"token", "credentials.json", ".env", ".netrc"}


class ModelPackError(RuntimeError):
    """The model pack or redistribution evidence is unsafe or incomplete."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _required_string(value: dict, key: str, where: str) -> str:
    result = str(value.get(key) or "").strip()
    if not result or result.casefold() in {"unknown", "unspecified", "tbd"}:
        raise ModelPackError(f"{where} requires verified {key}")
    return result


def validate_redistribution(metadata: dict) -> dict:
    upstream_id = _required_string(metadata, "upstream_id", "model")
    revision = _required_string(metadata, "revision", "model")
    license_name = _required_string(metadata, "license", "model")
    attribution = _required_string(metadata, "attribution", "model")
    redistribution = metadata.get("redistribution")
    if not isinstance(redistribution, dict) or redistribution.get("allowed") is not True:
        raise ModelPackError("model redistribution is not explicitly verified as allowed")
    verified_by = _required_string(redistribution, "verified_by", "redistribution")
    verified_at = _required_string(redistribution, "verified_at", "redistribution")
    terms = _required_string(redistribution, "terms", "redistribution")
    submodels = metadata.get("submodels")
    if not isinstance(submodels, list) or not submodels:
        raise ModelPackError("model submodels must be enumerated")
    normalized_submodels = []
    for index, item in enumerate(submodels):
        if not isinstance(item, dict):
            raise ModelPackError("invalid submodel metadata")
        where = f"submodel[{index}]"
        sub_redistribution = item.get("redistribution")
        if not isinstance(sub_redistribution, dict) or sub_redistribution.get("allowed") is not True:
            raise ModelPackError(f"{where} redistribution is not verified")
        normalized_submodels.append({
            "upstream_id": _required_string(item, "upstream_id", where),
            "revision": _required_string(item, "revision", where),
            "license": _required_string(item, "license", where),
            "attribution": _required_string(item, "attribution", where),
            "redistribution": {
                "allowed": True,
                "terms": _required_string(sub_redistribution, "terms", where),
            },
        })
    return {
        "upstream_id": upstream_id, "revision": revision, "license": license_name,
        "attribution": attribution,
        "redistribution": {"allowed": True, "terms": terms,
                           "verified_by": verified_by, "verified_at": verified_at},
        "submodels": normalized_submodels,
    }


def model_files(model_dir: Path) -> list[tuple[str, bytes]]:
    output = []
    for path in sorted(model_dir.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(model_dir).as_posix()
        pure = PurePosixPath(relative)
        if path.is_symlink() or not path.is_file() or pure.is_absolute() or ".." in pure.parts:
            raise ModelPackError(f"unsafe model file: {relative}")
        if any(part.casefold() in FORBIDDEN_NAMES or "credential" in part.casefold()
               for part in pure.parts):
            raise ModelPackError(f"credential-like model file: {relative}")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ModelPackError(f"model file exceeds safety limit: {relative}")
        output.append((relative, path.read_bytes()))
    if not output:
        raise ModelPackError("model directory is empty")
    return output


def safe_revision(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    if not result:
        raise ModelPackError("revision cannot form a safe pack name")
    return result


def build(model_dir: Path, metadata_path: Path, notices_path: Path, output_dir: Path) -> Path:
    model_dir = model_dir.resolve()
    metadata = validate_redistribution(json.loads(metadata_path.read_text(encoding="utf-8")))
    notices = notices_path.read_bytes()
    if not notices.strip():
        raise ModelPackError("THIRD_PARTY_NOTICES is empty")
    files = model_files(model_dir)
    root = f"diarization-runtime-community-1-{safe_revision(metadata['revision'])}"
    records = [{"path": f"models/{path}", "size": len(data), "sha256": sha256_bytes(data)}
               for path, data in files]
    manifest = {
        "schema": MODEL_PACK_SCHEMA,
        **metadata,
        "install_path": "models/pyannote/speaker-diarization-community-1",
        "files": records,
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
                      + "\n").encode("utf-8")
    payloads = [(f"models/{path}", data) for path, data in files] + [
        ("MODEL_MANIFEST.json", manifest_bytes),
        ("THIRD_PARTY_NOTICES.md", notices),
    ]
    sums = "".join(f"{sha256_bytes(data)}  {path}\n" for path, data in payloads).encode("utf-8")
    payloads.append(("SHA256SUMS", sums))
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{root}.zip"
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, data in payloads:
            info = zipfile.ZipInfo(f"{root}/{path}", (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Build verified diarization runtime pack")
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--notices", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(build(args.model_dir, args.metadata, args.notices, args.out))
    except (OSError, ValueError, json.JSONDecodeError, ModelPackError) as exc:
        print(f"[error] {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
