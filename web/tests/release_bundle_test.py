#!/usr/bin/env python3
"""Application Release Bundle boundaries using synthetic Git repositories only."""

from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_release_bundle as bundle  # noqa: E402


def command(root: Path, *args: str) -> None:
    subprocess.run(args, cwd=root, check=True, capture_output=True, text=True)


def write(root: Path, path: str, content: str = "synthetic\n") -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def repository(root: Path, tag: str | None = None) -> Path:
    command(root, "git", "init", "-q")
    command(root, "git", "config", "user.name", "Synthetic Release Test")
    command(root, "git", "config", "user.email", "synthetic@example.invalid")
    write(root, "README.md", "[简体中文](README.zh-CN.md)\n")
    write(root, "README.zh-CN.md", "[English](README.md)\n")
    write(root, "RELEASE_NOTES.md", "# Synthetic release notes\n")
    write(root, "VERSION", "0.15.1\n")
    write(root, "CHANGELOG.md", "## v0.15.1 — 2026-08-31\n")
    write(root, "Makefile")
    write(root, "pyproject.toml", '[project]\nname="synthetic"\nversion="0.15.1"\n')
    write(root, "safe/app.py")
    write(root, "speaker_bank/orgchart.template.json", "{}\n")
    write(root, "speaker_bank/private-voice.json", "{}\n")
    write(root, "meetings/private.txt")
    write(root, "private_reports/report.md")
    write(root, ".env", "TOKEN=fictional\n")
    write(root, "weights/model.gguf")
    write(root, "release/authorized-tag.txt", "v0.15.1\n")
    write(root, "release/bundle-include.txt", """README.md
README.zh-CN.md
RELEASE_NOTES.md
VERSION
CHANGELOG.md
Makefile
pyproject.toml
safe/**
speaker_bank/*.template.json
release/bundle-include.txt
release/authorized-tag.txt
""")
    command(root, "git", "add", ".")
    command(root, "git", "commit", "-qm", "synthetic fixture")
    if tag:
        command(root, "git", "tag", tag)
    return root


for unsafe in (
    "meetings/a.wav", "recordings/a.wav", "private_reports/report.md",
    ".env", ".env.local", "speaker_bank/person.json", "web/jobs/job.json",
    "docs/archive/old.md", "model.gguf", "cache/model.safetensors",
):
    assert bundle.forbidden_reason(unsafe), unsafe
assert bundle.forbidden_reason("speaker_bank/orgchart.template.json") is None
assert bundle.forbidden_reason("docs/runbooks/DISTRIBUTION.md") is None
assert bundle.allowed("web/static/app.js", ["web/static/**"])
assert not bundle.allowed("meetings/a.wav", ["web/static/**"])
assert bundle.allowed("web/server.py", ["web/*.py"])
assert not bundle.allowed("web/private/server.py", ["web/*.py"])

with tempfile.TemporaryDirectory(prefix="release-bundle-test-") as temp:
    repo = repository(Path(temp))
    write(repo, "safe/untracked.txt")
    result = bundle.build(
        repo, repo / "dist", repo / "release/bundle-include.txt", official=False)
    manifest = result["manifest"]
    paths = {item["path"] for item in manifest["files"]}
    assert manifest["schema"] == bundle.RELEASE_SCHEMA
    assert manifest["product_version"] == "0.15.1"
    assert manifest["official_release"] is False
    assert manifest["git_tag"] is None
    assert manifest["dirty"] is True  # untracked synthetic file is intentionally visible
    assert "safe/app.py" in paths
    assert "safe/untracked.txt" not in paths
    assert "speaker_bank/orgchart.template.json" in paths
    assert "release/authorized-tag.txt" in paths
    assert not any(path.startswith(("meetings/", "private_reports/", "weights/")) for path in paths)
    assert ".env" not in paths and "speaker_bank/private-voice.json" not in paths
    with zipfile.ZipFile(result["zip"]) as archive:
        zip_names = {name for name in archive.namelist() if not name.endswith("/")}
    with tarfile.open(result["tar"], "r:gz") as archive:
        tar_names = {member.name for member in archive.getmembers() if member.isfile()}
    assert zip_names == tar_names
    assert len({Path(name).parts[0] for name in zip_names}) == 1
    assert json.loads(result["manifest_path"].read_text()) == manifest
    try:
        bundle.build(repo, repo / "official", repo / "release/bundle-include.txt", official=True)
    except bundle.ReleaseError as exc:
        assert "clean Git worktree" in str(exc)
    else:
        raise AssertionError("dirty official bundle was accepted")

with tempfile.TemporaryDirectory(prefix="release-bundle-official-") as temp:
    repo = repository(Path(temp), tag="v0.15.1")
    result = bundle.build(
        repo, repo / "dist", repo / "release/bundle-include.txt", official=True)
    assert result["manifest"]["official_release"] is True
    assert result["manifest"]["git_tag"] == "v0.15.1"
    assert result["manifest"]["dirty"] is False

with tempfile.TemporaryDirectory(prefix="release-bundle-wrong-tag-") as temp:
    repo = repository(Path(temp), tag="v0.15.0")
    try:
        bundle.build(repo, repo / "dist", repo / "release/bundle-include.txt", official=True)
    except bundle.ReleaseError as exc:
        assert "requires exactly v0.15.1" in str(exc)
    else:
        raise AssertionError("mismatched release tag was accepted")

with tempfile.TemporaryDirectory(prefix="release-bundle-symlink-") as temp:
    repo = repository(Path(temp))
    (repo / "safe/escape").symlink_to("../VERSION")
    command(repo, "git", "add", "safe/escape")
    command(repo, "git", "commit", "-qm", "add synthetic symlink")
    try:
        bundle.build(repo, repo / "dist", repo / "release/bundle-include.txt")
    except bundle.ReleaseError as exc:
        assert "symlinks are not allowed" in str(exc)
    else:
        raise AssertionError("release symlink was accepted")

print("release bundle: allowlist, privacy, manifest, archives, dirty/tag and symlink guards passed")
