#!/usr/bin/env python3
"""Release metadata projections must agree with the root VERSION."""

from __future__ import annotations

import os
import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from build_release_bundle import RELEASE_SCHEMA, read_version  # noqa: E402

version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
assert re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version)
assert read_version(ROOT) == version
assert RELEASE_SCHEMA == "local-meeting-minutes-release/v1"

pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
project = pyproject["project"]
assert project["version"] == version
assert project["readme"] == "README.md"
assert pyproject["tool"]["setuptools"]["packages"] == []

bundle_allowlist = {
    line.strip()
    for line in (ROOT / "release" / "bundle-include.txt").read_text(
        encoding="utf-8"
    ).splitlines()
    if line.strip() and not line.lstrip().startswith("#")
}
assert "release/authorized-tag.txt" in bundle_allowlist

changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
assert re.search(rf"^## v{re.escape(version)} — \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.MULTILINE)

status = (ROOT / "docs" / "STATUS.md").read_text(encoding="utf-8")
assert f"产品版本：v{version}（release candidate）" in status

product_html = (ROOT / "web" / "static" / "product.html").read_text(encoding="utf-8")
major, minor, _ = version.split(".")
content_version = re.search(r'data-product-content-version="([0-9]+\.[0-9]+)"', product_html)
assert content_version and content_version.group(1) == f"{major}.{minor}"

for readme_name in ("README.md", "README.zh-CN.md"):
    readme = (ROOT / readme_name).read_text(encoding="utf-8")
    assert f"<!-- product-version: v{version} -->" in readme
    referenced = set(re.findall(r"\bv(\d+\.\d+\.\d+)\b", readme))
    assert referenced <= {version}, f"{readme_name} contains conflicting versions: {referenced}"

release_notes = ROOT / "docs" / "releases" / f"v{version}.md"
latest_release_notes = ROOT / "RELEASE_NOTES.md"
assert release_notes.is_file(), f"release notes missing: {release_notes}"
assert latest_release_notes.is_file(), "root RELEASE_NOTES.md is missing"
assert latest_release_notes.read_text(encoding="utf-8") == release_notes.read_text(encoding="utf-8")

release_tag = os.environ.get("RELEASE_TAG")
if release_tag:
    assert release_tag == f"v{version}", (
        f"release tag {release_tag!r} must equal VERSION v{version}"
    )
    assert release_notes == ROOT / "docs" / "releases" / f"{release_tag}.md"
    authorization = (ROOT / "release" / "authorized-tag.txt").read_text(
        encoding="utf-8"
    ).strip()
    assert authorization == release_tag, (
        f"release authorization {authorization!r} must equal {release_tag!r}"
    )

print(f"release metadata: VERSION, pyproject, changelog, status and README agree on v{version}")
