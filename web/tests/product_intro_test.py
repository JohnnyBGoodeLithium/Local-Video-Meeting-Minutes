#!/usr/bin/env python3
"""Product-introduction release, localization, and token contracts."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "web" / "static"
html = (STATIC / "product.html").read_text(encoding="utf-8")
script = (STATIC / "product.js").read_text(encoding="utf-8")
copy_source = (STATIC / "product-copy.js").read_text(encoding="utf-8")
foundation = (STATIC / "fluent-foundation.css").read_text(encoding="utf-8")
product_css = (STATIC / "product.css").read_text(encoding="utf-8")

# A MINOR or MAJOR version bump must update the product narrative baseline.
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
major, minor, _ = version.split(".")
content_version = re.search(r'data-product-content-version="([0-9]+\.[0-9]+)"', html)
assert content_version, "产品介绍页缺少 major.minor 内容基线"
assert content_version.group(1) == f"{major}.{minor}", (
    f"产品版本 v{version} 与介绍页内容基线 {content_version.group(1)} 不一致；"
    "MINOR/MAJOR 发布必须同步更新产品介绍"
)

# Every localized node has a checked English entry. Chinese remains the no-JS fallback.
html_keys = set(re.findall(r'data-i18n(?:-html|-aria)?="([A-Za-z][A-Za-z0-9]*)"', html))
copy_body = copy_source.split("export const EN_META", 1)[0]
english_keys = set(re.findall(r"^\s{2}([A-Za-z][A-Za-z0-9]*):", copy_body, re.MULTILINE))
assert html_keys == english_keys, (
    f"双语词典不完整：missing={sorted(html_keys - english_keys)}, "
    f"unused={sorted(english_keys - html_keys)}"
)
assert 'data-ui-language="zh-CN"' in html and 'data-ui-language="en"' in html
assert 'meeting-minutes:workspace:v1' in script, "介绍页语言必须与工作台共享偏好"
assert 'document.documentElement.lang = next' in script
assert 'EN_META.description' in script

# The page consumes the shared Fluent foundation and defines only its product-role layer.
assert '/static/fluent-foundation.css?v=' in html
assert 'data-fluent-theme="light"' in html
required_product_tokens = {
    "--productInk", "--productInkMuted", "--productCanvas", "--productStroke",
    "--productBrand", "--productIdentity", "--productEvidence", "--productKnowledge",
}
defined = set(re.findall(r"(--[\w-]+)\s*:", foundation + product_css))
assert required_product_tokens <= defined, (
    f"产品介绍语义 token 缺失：{sorted(required_product_tokens - defined)}"
)
bare_refs = set(re.findall(r"var\(\s*(--[\w-]+)\s*\)", product_css))
missing_refs = sorted(bare_refs - defined - {"--wave"})
assert not missing_refs, f"产品介绍引用未定义 token：{missing_refs}"

# Current v0.11+ product capabilities must not regress to the original p51 story.
for marker in (
    "Media Analysis Core", "MeetingPack", "WeKnora", "resource",
    "product-copy.js?v=20260828p104",
):
    assert marker in html + script + copy_source, f"产品介绍缺少当前能力标记：{marker}"

print(f"product intro: v{major}.{minor}, {len(html_keys)} bilingual keys, tokens resolved")
