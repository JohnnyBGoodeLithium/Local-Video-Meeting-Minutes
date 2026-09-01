#!/usr/bin/env python3
"""Release metadata projections must agree with the root VERSION."""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
assert re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version)

pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
project = pyproject["project"]
assert project["version"] == version
assert project["readme"] == "README.md"
assert pyproject["tool"]["setuptools"]["packages"] == []

changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
assert re.search(rf"^## v{re.escape(version)} — \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.MULTILINE)

status = (ROOT / "docs" / "STATUS.md").read_text(encoding="utf-8")
assert f"产品版本：v{version}" in status

product_html = (ROOT / "web" / "static" / "product.html").read_text(encoding="utf-8")
major, minor, _ = version.split(".")
content_version = re.search(r'data-product-content-version="([0-9]+\.[0-9]+)"', product_html)
assert content_version and content_version.group(1) == f"{major}.{minor}"

for readme_name in ("README.md", "README.zh-CN.md"):
    readme = (ROOT / readme_name).read_text(encoding="utf-8")
    assert f"<!-- product-version: v{version} -->" in readme
    referenced = set(re.findall(r"\bv(\d+\.\d+\.\d+)\b", readme))
    assert referenced <= {version}, f"{readme_name} contains conflicting versions: {referenced}"

release_tag = os.environ.get("RELEASE_TAG")
if release_tag:
    assert release_tag == f"v{version}", (
        f"release tag {release_tag!r} must equal VERSION v{version}"
    )

print(f"release metadata: VERSION, pyproject, changelog, status and README agree on v{version}")
