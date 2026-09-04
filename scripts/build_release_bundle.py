#!/usr/bin/env python3
"""Build a sanitized Application Release Bundle from a tracked-file allowlist."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import stat
import subprocess
import sys
import tarfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


RELEASE_SCHEMA = "local-meeting-minutes-release/v1"
ARCHIVE_PREFIX = "local-video-meeting-minutes"
FORBIDDEN_ROOTS = {
    ".git", ".github", ".venv", ".cache", "dist", "recordings", "meetings",
    "evaluations", "private_reports",
}
FORBIDDEN_DIR_NAMES = {
    "__pycache__", ".pytest_cache", ".ruff_cache",
}
FORBIDDEN_DOC_DIRS = {
    "docs/archive", "docs/history", "docs/research", "docs/screenshots",
}
MODEL_SUFFIXES = {
    ".bin", ".ckpt", ".gguf", ".onnx", ".pt", ".pth", ".safetensors",
}
CREDENTIAL_NAMES = {
    "credentials.json", "id_rsa", "id_ed25519", "service-account.json",
}
MAX_FILE_BYTES = 50 * 1024 * 1024


class ReleaseError(RuntimeError):
    """A release boundary was violated."""


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def read_version(root: Path) -> str:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ReleaseError(f"VERSION is not SemVer: {version!r}")
    return version


def load_allowlist(path: Path) -> list[str]:
    rules = []
    for line in path.read_text(encoding="utf-8").splitlines():
        rule = line.strip()
        if not rule or rule.startswith("#"):
            continue
        pure = PurePosixPath(rule)
        if pure.is_absolute() or ".." in pure.parts:
            raise ReleaseError(f"unsafe allowlist rule: {rule}")
        rules.append(rule)
    if not rules:
        raise ReleaseError("release allowlist is empty")
    return rules


def allowed(path: str, rules: list[str]) -> bool:
    for rule in rules:
        if rule.endswith("/**"):
            prefix = rule[:-3].rstrip("/")
            if path == prefix or path.startswith(prefix + "/"):
                return True
        elif any(char in rule for char in "*?["):
            if PurePosixPath(path).match(rule):
                return True
        elif path == rule:
            return True
    return False


def forbidden_reason(path: str) -> str | None:
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        return "absolute or parent path"
    if not pure.parts:
        return "empty path"
    if pure.parts[0] in FORBIDDEN_ROOTS:
        return f"forbidden root {pure.parts[0]}"
    if any(part in FORBIDDEN_DIR_NAMES for part in pure.parts):
        return "runtime cache directory"
    normalized = pure.as_posix()
    if any(normalized == item or normalized.startswith(item + "/") for item in FORBIDDEN_DOC_DIRS):
        return "non-distribution documentation"
    if normalized == "web/jobs" or normalized.startswith("web/jobs/"):
        return "runtime job data"
    if pure.parts[0] == "speaker_bank" and not pure.name.endswith(".template.json"):
        return "non-template speaker bank content"
    lower_name = pure.name.lower()
    if lower_name == ".env" or lower_name.startswith(".env."):
        return "environment file"
    if lower_name in CREDENTIAL_NAMES or "credential" in lower_name or "api_key" in lower_name:
        return "credential-like file"
    if lower_name.endswith(".log") or lower_name.endswith(".meetingpack.zip"):
        return "runtime output"
    if pure.suffix.lower() in MODEL_SUFFIXES:
        return "model weight or binary"
    return None


def tracked_files(root: Path) -> dict[str, int]:
    raw = subprocess.run(
        ["git", "ls-files", "--stage", "-z"], cwd=root,
        capture_output=True, check=True,
    ).stdout.decode("utf-8")
    tracked: dict[str, int] = {}
    for entry in raw.split("\0"):
        if not entry:
            continue
        metadata, path = entry.split("\t", 1)
        mode = int(metadata.split()[0], 8)
        tracked[path] = mode
    return tracked


def select_files(root: Path, allowlist: Path) -> list[tuple[str, int]]:
    rules = load_allowlist(allowlist)
    selected = []
    for path, mode in tracked_files(root).items():
        if not allowed(path, rules):
            continue
        reason = forbidden_reason(path)
        if reason:
            raise ReleaseError(f"allowlisted path rejected ({reason}): {path}")
        source = root / path
        if stat.S_ISLNK(source.lstat().st_mode) or mode == 0o120000:
            raise ReleaseError(f"symlinks are not allowed in release bundles: {path}")
        if not source.is_file():
            raise ReleaseError(f"tracked release entry is not a regular file: {path}")
        if source.stat().st_size > MAX_FILE_BYTES:
            raise ReleaseError(f"release file exceeds {MAX_FILE_BYTES} bytes: {path}")
        selected.append((path, mode))
    selected.sort()
    required = {
        "README.md", "README.zh-CN.md", "RELEASE_NOTES.md", "VERSION",
        "pyproject.toml", "Makefile",
    }
    missing = required - {path for path, _ in selected}
    if missing:
        raise ReleaseError(f"release allowlist missed required files: {sorted(missing)}")
    return selected


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def commit_timestamp(root: Path) -> tuple[int, str]:
    epoch = int(git(root, "show", "-s", "--format=%ct", "HEAD"))
    iso = datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")
    return epoch, iso


def archive_context(root: Path, official: bool) -> dict:
    version = read_version(root)
    commit = git(root, "rev-parse", "HEAD")
    dirty = bool(git(root, "status", "--porcelain"))
    tags = sorted(filter(None, git(root, "tag", "--points-at", "HEAD").splitlines()))
    expected_tag = f"v{version}"
    if official:
        if dirty:
            raise ReleaseError("official release requires a clean Git worktree")
        if tags != [expected_tag]:
            raise ReleaseError(
                f"official release requires exactly {expected_tag} on HEAD; found {tags}"
            )
        identifier = expected_tag
        tag = expected_tag
    else:
        identifier = f"v{version}-dev-g{commit[:7]}" + ("-dirty" if dirty else "")
        tag = None
    epoch, generated_at = commit_timestamp(root)
    if dirty:
        epoch = int(time.time())
        generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "version": version, "commit": commit, "dirty": dirty, "tag": tag,
        "official": official, "identifier": identifier, "epoch": epoch,
        "generated_at": generated_at,
    }


def zip_timestamp(epoch: int) -> tuple[int, int, int, int, int, int]:
    tm = time.gmtime(max(epoch, 315532800))
    return (tm.tm_year, tm.tm_mon, tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec)


def build(root: Path, output_dir: Path, allowlist: Path, official: bool = False) -> dict:
    root = root.resolve()
    output_dir = output_dir.resolve()
    context = archive_context(root, official)
    selected = select_files(root, allowlist)
    archive_root = f"{ARCHIVE_PREFIX}-{context['identifier']}"
    file_records = []
    payloads: list[tuple[str, int, bytes]] = []
    for path, mode in selected:
        content = (root / path).read_bytes()
        payloads.append((path, mode, content))
        file_records.append({
            "path": path,
            "sha256": sha256_bytes(content),
            "size": len(content),
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{archive_root}.zip"
    tar_path = output_dir / f"{archive_root}.tar.gz"
    manifest_path = output_dir / "release-manifest.json"
    checksums_path = output_dir / "SHA256SUMS"
    manifest = {
        "schema": RELEASE_SCHEMA,
        "product_version": context["version"],
        "git_commit": context["commit"],
        "git_tag": context["tag"],
        "official_release": context["official"],
        "dirty": context["dirty"],
        "generated_at": context["generated_at"],
        "python": "3.11",
        "archive_root": archive_root,
        "assets": {"zip": zip_path.name, "tar_gz": tar_path.name},
        "files": file_records,
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    archive_payloads = payloads + [("release-manifest.json", 0o100644, manifest_bytes)]

    for path in (zip_path, tar_path, manifest_path, checksums_path):
        if path.exists():
            path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, mode, content in archive_payloads:
            info = zipfile.ZipInfo(f"{archive_root}/{path}", zip_timestamp(context["epoch"]))
            info.create_system = 3
            info.external_attr = ((0o755 if mode == 0o100755 else 0o644) & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)

    with tar_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=context["epoch"]) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path, mode, content in archive_payloads:
                    info = tarfile.TarInfo(f"{archive_root}/{path}")
                    info.size = len(content)
                    info.mtime = context["epoch"]
                    info.mode = 0o755 if mode == 0o100755 else 0o644
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    import io
                    archive.addfile(info, io.BytesIO(content))

    manifest_path.write_bytes(manifest_bytes)
    checksum_lines = []
    for asset in (tar_path, zip_path, manifest_path):
        checksum_lines.append(f"{sha256_bytes(asset.read_bytes())}  {asset.name}")
    checksums_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    return {
        "manifest": manifest,
        "zip": zip_path,
        "tar": tar_path,
        "manifest_path": manifest_path,
        "checksums": checksums_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--allowlist", type=Path, default=None)
    parser.add_argument("--official", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    output = (args.output_dir or root / "dist").resolve()
    allowlist = (args.allowlist or root / "release" / "bundle-include.txt").resolve()
    result = build(root, output, allowlist, official=args.official)
    print(json.dumps({
        "archive_root": result["manifest"]["archive_root"],
        "official_release": result["manifest"]["official_release"],
        "dirty": result["manifest"]["dirty"],
        "files": len(result["manifest"]["files"]),
        "assets": [str(result["tar"]), str(result["zip"]),
                   str(result["manifest_path"]), str(result["checksums"])],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
