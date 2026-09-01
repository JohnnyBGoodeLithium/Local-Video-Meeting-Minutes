#!/usr/bin/env python3
"""Public product-site narrative, localization, and safety contracts.

The product site uses fictional Northstar data only. This test reads source files and
never enumerates local meetings, recordings, jobs, or speaker data.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "web" / "static"
html = (STATIC / "product.html").read_text(encoding="utf-8")
script = (STATIC / "product.js").read_text(encoding="utf-8")
demo_script = (STATIC / "product-demo.js").read_text(encoding="utf-8")
copy_source = (STATIC / "product-copy.js").read_text(encoding="utf-8")
foundation = (STATIC / "fluent-foundation.css").read_text(encoding="utf-8")
product_css = (STATIC / "product.css").read_text(encoding="utf-8")

# A MINOR or MAJOR version bump must update both product-content markers.
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
major, minor, _ = version.split(".")
expected_content_version = f"{major}.{minor}"
html_version = re.search(r'data-product-content-version="([0-9]+\.[0-9]+)"', html)
meta_version = re.search(
    r'<meta name="product-content-version" content="([0-9]+\.[0-9]+)">', html,
)
assert html_version and meta_version, "产品介绍页缺少一致的内容版本标记"
assert html_version.group(1) == meta_version.group(1) == expected_content_version, (
    f"产品版本 v{version} 与介绍页内容基线不一致"
)

# Seven sections tell one user journey; deleted technical chapters cannot return.
section_tags = re.findall(r"<section\b([^>]*)>", html)
section_ids = [
    re.search(r'id="([^"]+)"', attributes).group(1)
    for attributes in section_tags if "data-product-section" in attributes
]
assert section_ids == [
    "overview", "find", "verify", "correct", "reuse", "use-cases", "trust",
], f"产品页一级信息架构漂移：{section_ids}"
for removed_id in ("identity", "capabilities", "architecture", "cores", "experience"):
    assert f'id="{removed_id}"' not in html, f"旧技术章节重新出现：{removed_id}"

required_journey = (
    "两小时会议，不该再花两小时复盘。",
    "不从 00:00 开始，从真正重要的人或议题开始。",
    "每一条重要结论，都能回到原始证据。",
    "发现错误，不必从头再来。",
    "核对过的会议和视频，可以继续交给下一步。",
    "MeetingPack", "AI Context", "Knowledge Base &amp; RAG",
    "虚构演示数据", "Northstar Launch Review", "Northstar Product Launch",
)
for marker in required_journey:
    assert marker in html, f"产品页缺少用户旅程标记：{marker}"

# Chinese is the no-JS baseline; each projected node has exactly one English entry.
html_keys = set(re.findall(r'data-i18n(?:-html|-aria)?="([A-Za-z][A-Za-z0-9]*)"', html))
copy_body = copy_source.split("export const EN_META", 1)[0]
english_keys = set(re.findall(r"^\s{2}([A-Za-z][A-Za-z0-9]*):", copy_body, re.MULTILINE))
runtime_keys = set(re.findall(r"EN_COPY\.([A-Za-z][A-Za-z0-9]*)", script))
used_english_keys = html_keys | runtime_keys
assert used_english_keys == english_keys, (
    f"双语词典不完整：missing={sorted(used_english_keys - english_keys)}, "
    f"unused={sorted(english_keys - used_english_keys)}"
)
assert len(html_keys) >= 100, "产品页双语投影意外缩水"
assert 'data-ui-language="zh-CN"' in html and 'data-ui-language="en"' in html
assert 'meeting-minutes:workspace:v1' in script, "介绍页语言必须与工作台共享偏好"
assert 'document.documentElement.lang = next' in script
assert 'EN_META.description' in script and 'meta[property="og:title"]' in script

# Meeting is visible without JavaScript; video, evidence, and correction are real controls.
assert 'data-demo-panel="meeting"' in html
assert re.search(r'data-demo-panel="video" hidden', html)
assert 'data-demo-mode="meeting"' in html and 'data-demo-mode="video"' in html
assert 'data-demo-evidence' in html and 'aria-expanded="false"' in html
assert 'data-correction-toggle' in html and 'aria-live="polite"' in html
assert "enhanceProductDemo" in script and "resolveDemoState" in demo_script
assert "prefers-reduced-motion: reduce" in product_css

# The public demo is hard-coded, visibly fictional, and does not touch meeting data APIs.
public_sources = html + script + demo_script + copy_source
assert "DEMO_STATES" in copy_source and "Fictional demo data" in copy_source
for forbidden_api in ("/api/meetings", "/api/import-url", "WebSocket(", "EventSource("):
    assert forbidden_api not in public_sources, f"产品演示不得访问真实数据：{forbidden_api}"
for forbidden_term in (
    "KnowledgeSink", "Agent-ready", "multi-stage pipeline", "Map/Reduce",
    "reranker", "embedding", "provider-neutral", "Voice ID", "Person ID",
    "Org Node", "Turn ID", "Page ID", "Claim ID", "canonical", "revision",
):
    assert forbidden_term.lower() not in public_sources.lower(), (
        f"普通阅读路径残留内部实现词：{forbidden_term}"
    )
assert "https://fonts." not in html and "analytics" not in html.lower()

# Internal anchors resolve; the technical route is an explicit public GitHub link.
ids = set(re.findall(r'id="([^"]+)"', html))
for target in re.findall(r'href="#([^"]+)"', html):
    assert target in ids, f"产品页存在失效锚点：#{target}"
assert "github.com/JohnnyBGoodeLithium/Local-Video-Meeting-Minutes/blob/main/" in html
assert '<meta property="og:type" content="website">' in html
assert '<meta name="twitter:card" content="summary">' in html

# Source Fold tokens and its product-derived structure must remain resolved.
expected_tokens = {
    "--productInk": "#18263a", "--productInkMuted": "#5c6b7e",
    "--productCanvas": "#f4f7fb", "--productSurface": "#ffffff",
    "--productStroke": "#c9d4e2", "--productBrand": "#a3384a",
    "--productBrandHover": "#852b3b", "--productIdentity": "#32705a",
    "--productEvidence": "#a3384a", "--productSuccess": "#32705a",
}
for token, value in expected_tokens.items():
    assert re.search(rf"{re.escape(token)}:\s*{re.escape(value)}\b", product_css, re.I), (
        f"Source Fold token 漂移：{token}"
    )
assert 'data-design-direction="source-fold"' in html
assert "--foldShadow" in product_css and "clip-path: polygon" in product_css
assert "grid-column: 1 / 9" in product_css, "主标题与副标题必须共享左侧栅格"
assert ".demo-window-bar i" not in product_css, "不得恢复浏览器三圆点装饰"
assert "hero-steps" not in html + product_css, "不得恢复装饰编号步骤"
defined = set(re.findall(r"(--[\w-]+)\s*:", foundation + product_css))
bare_refs = set(re.findall(r"var\(\s*(--[\w-]+)\s*\)", product_css))
missing_refs = sorted(bare_refs - defined - {"--wave", "--at", "--length", "--start"})
assert not missing_refs, f"产品介绍引用未定义 token：{missing_refs}"

print(
    f"product site: v{expected_content_version}, seven sections, "
    f"{len(html_keys)} bilingual keys, fictional demo and tokens passed"
)
