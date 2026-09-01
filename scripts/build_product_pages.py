#!/usr/bin/env python3
"""Build the public product site as a data-free GitHub Pages artifact."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web" / "static"
REPOSITORY_URL = "https://github.com/JohnnyBGoodeLithium/Local-Video-Meeting-Minutes"
ASSETS = (
    "fluent-foundation.css",
    "product.css",
    "product.js",
    "product-copy.js",
    "product-demo.js",
)


def build(output: Path) -> None:
    output = output.resolve()
    if output == ROOT or output == ROOT.parent:
        raise ValueError("Refusing to replace the repository or its parent")
    output.parent.mkdir(parents=True, exist_ok=True)

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    html = (STATIC / "product.html").read_text(encoding="utf-8")
    html = html.replace(
        'data-design-direction="source-fold"',
        f'data-design-direction="source-fold" data-static-product-version="{version}"',
    )
    html = html.replace('href="/static/', 'href="static/')
    html = html.replace('src="/static/', 'src="static/')
    html = html.replace('href="/"', f'href="{REPOSITORY_URL}"')
    html = html.replace(
        'data-i18n="openWorkspace">打开工作台',
        'data-i18n="viewRepository">查看安装方式',
    )
    html = html.replace(
        'data-i18n-aria="brandBackAria" aria-label="返回会议工作台"',
        'data-i18n-aria="brandBackAria" aria-label="查看项目仓库"',
    )

    with tempfile.TemporaryDirectory(prefix="product-pages-", dir=output.parent) as tmp:
        stage = Path(tmp)
        static_output = stage / "static"
        static_output.mkdir()
        (stage / "index.html").write_text(html, encoding="utf-8")
        (stage / ".nojekyll").write_text("", encoding="utf-8")
        for asset in ASSETS:
            source = STATIC / asset
            content = source.read_text(encoding="utf-8")
            if asset == "product-copy.js":
                content = content.replace(
                    '  openWorkspace: "Open workspace",',
                    '  viewRepository: "View setup",',
                ).replace(
                    '  brandBackAria: "Back to meeting workspace",',
                    '  brandBackAria: "View project repository",',
                )
            (static_output / asset).write_text(content, encoding="utf-8")

        rendered = (stage / "index.html").read_text(encoding="utf-8")
        if 'href="/static/' in rendered or 'src="/static/' in rendered:
            raise RuntimeError("Pages artifact still contains root-relative static assets")
        if output.exists():
            if not output.is_dir():
                raise ValueError(f"Output exists and is not a directory: {output}")
            shutil.rmtree(output)
        shutil.copytree(stage, output)

    print(f"product pages: v{version}, {len(ASSETS) + 2} files -> {output}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "product-site")
    args = parser.parse_args()
    build(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
