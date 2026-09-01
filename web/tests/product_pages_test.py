#!/usr/bin/env python3
"""Verify the public Pages artifact stays portable and data-free."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


with tempfile.TemporaryDirectory(prefix="product-pages-test-") as tmp:
    output = Path(tmp) / "site"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_product_pages.py"),
         "--output", str(output)],
        cwd=ROOT,
        check=True,
    )
    files = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    }
    assert files == {
        ".nojekyll",
        "index.html",
        "static/fluent-foundation.css",
        "static/product-copy.js",
        "static/product-demo.js",
        "static/product.css",
        "static/product.js",
    }, files
    html = (output / "index.html").read_text(encoding="utf-8")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert f'data-static-product-version="{version}"' in html
    assert 'data-design-direction="source-fold"' in html
    assert 'href="/static/' not in html and 'src="/static/' not in html
    assert 'href="/"' not in html
    assert "查看安装方式" in html and 'data-i18n="viewRepository"' in html
    assert "recordings/" not in html and "private_reports/" not in html
    copy_source = (output / "static" / "product-copy.js").read_text(encoding="utf-8")
    assert 'viewRepository: "View setup"' in copy_source
    assert 'openWorkspace: "Open workspace"' not in copy_source

print("product pages: portable static assets, version and privacy boundary passed")
