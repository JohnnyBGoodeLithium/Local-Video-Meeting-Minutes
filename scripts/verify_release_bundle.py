#!/usr/bin/env python3
"""Verify Application Release Bundle structure, metadata, hashes, and privacy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

from build_release_bundle import RELEASE_SCHEMA, forbidden_reason


class VerificationError(RuntimeError):
    """A built asset violated its release contract."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_member_path(raw: str) -> PurePosixPath:
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise VerificationError(f"unsafe archive path: {raw}")
    return path


def extract_zip(archive_path: Path, destination: Path) -> set[str]:
    names: set[str] = set()
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            path = safe_member_path(info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise VerificationError(f"ZIP symlink is forbidden: {path}")
            if info.is_dir():
                continue
            if path.as_posix() in names:
                raise VerificationError(f"duplicate ZIP entry is forbidden: {path}")
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            names.add(path.as_posix())
    return names


def extract_tar(archive_path: Path, destination: Path) -> set[str]:
    names: set[str] = set()
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            path = safe_member_path(member.name)
            if member.isdir():
                continue
            if not member.isfile():
                raise VerificationError(f"tar symlink or special entry is forbidden: {path}")
            if path.as_posix() in names:
                raise VerificationError(f"duplicate tar entry is forbidden: {path}")
            source = archive.extractfile(member)
            if source is None:
                raise VerificationError(f"tar entry cannot be read: {path}")
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())
            names.add(path.as_posix())
    return names


def one_top_level(names: set[str]) -> str:
    roots = {PurePosixPath(name).parts[0] for name in names}
    if len(roots) != 1:
        raise VerificationError(f"archive must have one top-level directory: {sorted(roots)}")
    return next(iter(roots))


def verify_checksums(dist: Path, expected_assets: set[str]) -> None:
    lines = (dist / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    parsed = {}
    for line in lines:
        digest, name = line.split("  ", 1)
        parsed[name] = digest
    if set(parsed) != expected_assets:
        raise VerificationError(
            f"SHA256SUMS assets differ: expected={sorted(expected_assets)} actual={sorted(parsed)}"
        )
    for name, digest in parsed.items():
        if sha256(dist / name) != digest:
            raise VerificationError(f"asset checksum mismatch: {name}")


def verify_tree(root: Path, manifest: dict) -> None:
    required = {
        "README.md", "README.zh-CN.md", "VERSION", "CHANGELOG.md",
        "SECURITY.md", "CONTRIBUTING.md", "Makefile", "pyproject.toml",
        "requirements/runtime.lock", "requirements/ci.lock",
        "web/static/index.html", "web/tests/run_smoke.py",
        "prompts/orgchart_extract.md", "docs/runbooks/DISTRIBUTION.md",
        "release-manifest.json",
    }
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*") if path.is_file()
    }
    missing = required - actual
    if missing:
        raise VerificationError(f"required bundle files missing: {sorted(missing)}")

    for relative in sorted(actual):
        if relative == "release-manifest.json":
            continue
        reason = forbidden_reason(relative)
        if reason:
            raise VerificationError(f"forbidden archive entry ({reason}): {relative}")
        if os.path.isabs(relative) or ".." in PurePosixPath(relative).parts:
            raise VerificationError(f"unsafe extracted path: {relative}")

    records = manifest.get("files")
    if not isinstance(records, list):
        raise VerificationError("manifest files must be a list")
    paths = [record.get("path") for record in records]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise VerificationError("manifest file order must be stable and unique")
    if set(paths) != actual - {"release-manifest.json"}:
        raise VerificationError("manifest file set differs from extracted bundle")
    for record in records:
        path = root / record["path"]
        if path.stat().st_size != record["size"] or sha256(path) != record["sha256"]:
            raise VerificationError(f"manifest hash or size mismatch: {record['path']}")

    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if manifest.get("product_version") != version:
        raise VerificationError("manifest product version differs from VERSION")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if project.get("version") != version:
        raise VerificationError("pyproject version differs from VERSION")
    english = (root / "README.md").read_text(encoding="utf-8")
    chinese = (root / "README.zh-CN.md").read_text(encoding="utf-8")
    if "[简体中文](README.zh-CN.md)" not in english or "[English](README.md)" not in chinese:
        raise VerificationError("README language links are incomplete")
    if manifest.get("official_release"):
        if manifest.get("dirty") or manifest.get("git_tag") != f"v{version}":
            raise VerificationError("official release manifest is not clean and version-tagged")
    elif manifest.get("git_tag") is not None:
        raise VerificationError("development bundle must not claim a release tag")


def verify(dist: Path, full: bool = False) -> dict:
    dist = dist.resolve()
    manifest_path = dist / "release-manifest.json"
    checksum_path = dist / "SHA256SUMS"
    if not manifest_path.is_file() or not checksum_path.is_file():
        raise VerificationError("release-manifest.json and SHA256SUMS are required")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != RELEASE_SCHEMA:
        raise VerificationError(f"unsupported manifest schema: {manifest.get('schema')}")
    assets = manifest.get("assets") or {}
    zip_path = dist / str(assets.get("zip") or "")
    tar_path = dist / str(assets.get("tar_gz") or "")
    if not zip_path.is_file() or not tar_path.is_file():
        raise VerificationError("manifest archive assets are missing")
    verify_checksums(dist, {zip_path.name, tar_path.name, manifest_path.name})

    with tempfile.TemporaryDirectory(prefix="meeting-release-verify-") as temp:
        temp_root = Path(temp)
        zip_extract = temp_root / "zip"
        tar_extract = temp_root / "tar"
        zip_names = extract_zip(zip_path, zip_extract)
        tar_names = extract_tar(tar_path, tar_extract)
        if zip_names != tar_names:
            raise VerificationError("ZIP and tar.gz file sets differ")
        zip_top = one_top_level(zip_names)
        tar_top = one_top_level(tar_names)
        if zip_top != tar_top or zip_top != manifest.get("archive_root"):
            raise VerificationError("archive top-level directory differs from manifest")
        zip_root = zip_extract / zip_top
        tar_root = tar_extract / tar_top
        internal_zip = json.loads((zip_root / "release-manifest.json").read_text(encoding="utf-8"))
        internal_tar = json.loads((tar_root / "release-manifest.json").read_text(encoding="utf-8"))
        if internal_zip != manifest or internal_tar != manifest:
            raise VerificationError("internal and external manifests differ")
        verify_tree(zip_root, manifest)
        verify_tree(tar_root, manifest)
        if full:
            subprocess.run(
                [sys.executable, str(zip_root / "scripts" / "smoke_release_bundle.py"),
                 "--root", str(zip_root)],
                cwd=zip_root, check=True,
            )
    return {
        "archive_root": manifest["archive_root"],
        "files": len(manifest["files"]),
        "official_release": manifest["official_release"],
        "dirty": manifest["dirty"],
        "full": full,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, default=Path(__file__).resolve().parents[1] / "dist")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.dist, full=args.full), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
