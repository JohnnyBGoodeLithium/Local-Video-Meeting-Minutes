#!/usr/bin/env python3
"""Verify paths, hashes, manifest, and redistribution gate of a model pack."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import PurePosixPath
import zipfile

from build_diarization_runtime_pack import (MODEL_PACK_SCHEMA, ModelPackError,
                                             validate_redistribution)


def verify(path) -> dict:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos if not info.is_dir()]
        if len(names) != len(set(names)):
            raise ModelPackError("duplicate model pack entry")
        roots = {PurePosixPath(name).parts[0] for name in names}
        if len(roots) != 1:
            raise ModelPackError("model pack must have one root")
        root = next(iter(roots))
        for name in names:
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or len(pure.parts) < 2:
                raise ModelPackError("unsafe model pack path")
            mode = (archive.getinfo(name).external_attr >> 16) & 0o170000
            if mode not in {0, 0o100000}:
                raise ModelPackError("model pack symlink or special entry")
        required = {f"{root}/MODEL_MANIFEST.json", f"{root}/THIRD_PARTY_NOTICES.md",
                    f"{root}/SHA256SUMS"}
        if not required <= set(names):
            raise ModelPackError("model pack metadata is incomplete")
        manifest = json.loads(archive.read(f"{root}/MODEL_MANIFEST.json"))
        if manifest.get("schema") != MODEL_PACK_SCHEMA:
            raise ModelPackError("unsupported model pack schema")
        validate_redistribution(manifest)
        sums = {}
        for line in archive.read(f"{root}/SHA256SUMS").decode("utf-8").splitlines():
            digest, relative = line.split("  ", 1)
            sums[relative] = digest
        expected = {PurePosixPath(name).relative_to(root).as_posix() for name in names} \
            - {"SHA256SUMS"}
        if set(sums) != expected:
            raise ModelPackError("model pack checksum file set differs")
        for relative, digest in sums.items():
            if hashlib.sha256(archive.read(f"{root}/{relative}")).hexdigest() != digest:
                raise ModelPackError(f"model pack checksum mismatch: {relative}")
        model_records = manifest.get("files")
        if not isinstance(model_records, list) or not model_records:
            raise ModelPackError("model manifest file records are empty")
        for record in model_records:
            relative = str(record.get("path") or "")
            data = archive.read(f"{root}/{relative}")
            if len(data) != record.get("size") or hashlib.sha256(data).hexdigest() != record.get("sha256"):
                raise ModelPackError(f"model manifest mismatch: {relative}")
        return {"root": root, "files": len(model_records),
                "upstream_id": manifest["upstream_id"], "revision": manifest["revision"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify diarization runtime pack")
    parser.add_argument("pack")
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.pack), sort_keys=True))
    except (OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile,
            ModelPackError) as exc:
        print(f"[error] {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
