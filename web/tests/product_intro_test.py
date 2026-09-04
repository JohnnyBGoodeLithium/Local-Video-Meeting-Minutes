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

# Nine sections tell one user journey; deleted technical chapters cannot return.
section_tags = re.findall(r"<section\b([^>]*)>", html)
section_ids = [
    re.search(r'id="([^"]+)"', attributes).group(1)
    for attributes in section_tags if "data-product-section" in attributes
]
assert section_ids == [
    "overview", "meeting-video", "find", "verify", "correct", "review-anywhere",
    "playback", "live", "reuse",
], f"产品页一级信息架构漂移：{section_ids}"
for removed_id in (
    "identity", "capabilities", "architecture", "cores", "experience", "use-cases", "trust",
):
    assert f'id="{removed_id}"' not in html, f"旧技术章节重新出现：{removed_id}"

required_journey = (
    "两小时会议，不该再花两小时复盘。",
    "同一套可信上下文，两种不同的回顾起点。",
    "不从 00:00 开始，从真正重要的人或议题开始。",
    "每一条重要结论，都能回到原始证据。",
    "发现错误，不必从头再来。",
    "从结论回到这段讨论，不丢人物、时间和画面。",
    "Live Context · Experimental",
    "虚构演示数据", "Northstar Launch Review", "Northstar Product Launch",
)
for marker in required_journey:
    assert marker in html, f"产品页缺少用户旅程标记：{marker}"

# Review surfaces and continuation layers are separate parts of one story.
assert 'data-review-group="surfaces"' in html
assert 'data-review-group="continuation"' in html
assert re.findall(r'data-review-surface="([^"]+)"', html) == [
    "workbench", "companion", "meetingpack",
]
assert re.findall(r'data-continuation-layer="([^"]+)"', html) == [
    "minutes", "knowledge",
]
for capability in ("Send", "Track", "Review", "Verify"):
    assert f'companion{capability}Label' in html
assert 'data-i18n="reuseBridge"' in html

# Locked Chinese and English copy share the same keys in product-copy.js.
html_keys = set(re.findall(r'data-i18n(?:-html|-aria)?="([A-Za-z][A-Za-z0-9]*)"', html))
zh_body = re.search(
    r"export const ZH_COPY = Object\.freeze\(\{(.*?)\}\);",
    copy_source, re.DOTALL,
).group(1)
en_body = re.search(
    r"export const EN_COPY = Object\.freeze\(\{(.*?)\}\);",
    copy_source, re.DOTALL,
).group(1)
zh_keys = set(re.findall(r"^\s{2}([A-Za-z][A-Za-z0-9]*):", zh_body, re.MULTILINE))
english_keys = set(re.findall(r"^\s{2}([A-Za-z][A-Za-z0-9]*):", en_body, re.MULTILINE))
review_html = html[html.index('<section id="review-anywhere"'):html.index('<section id="playback"')]
closing_html = html[html.index('<div class="final-cta"'):html.index("</main>")]
locked_keys = set(re.findall(
    r'data-i18n="([A-Za-z][A-Za-z0-9]*)"', review_html + closing_html,
))
locked_keys.discard("pocBoundary")
assert zh_keys == locked_keys, (
    f"锁定中文词典键漂移：missing={sorted(locked_keys - zh_keys)}, "
    f"unused={sorted(zh_keys - locked_keys)}"
)
assert locked_keys <= english_keys, (
    f"锁定英文词典缺键：{sorted(locked_keys - english_keys)}"
)
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
assert 'import { EN_COPY, EN_META, ZH_COPY }' in script

for marker in (
    "深度处理留在本机，回顾跟着你走。",
    "回顾发生在哪里",
    "发送", "跟进", "回顾", "核对",
    "结果如何继续",
    "纪要讲清这一次，知识库连接下一次。",
    "下一次，不必从头开始。",
    "Heavy processing stays local. Review follows you.",
    "WHERE REVIEW HAPPENS",
    "WHAT CONTINUES",
    "Minutes make this session clear. The knowledge base carries it into the next task.",
    "The next task does not have to start from zero.",
):
    assert marker in copy_source, f"锁定产品文案缺失：{marker}"

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
    "Transport does not define the product experience",
    "Implemented / validating",
    "Hosted Chromium",
    "Tailscale transport",
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
assert ".final-cta::before" not in product_css, "CTA 不得恢复贯穿 section 的 rail"
assert ".final-cta-content::before" in product_css
assert "height: 100vh" not in product_css and "min-height: 100vh" not in product_css
assert "scroll-snap" not in product_css
assert "text-wrap: balance" in product_css
defined = set(re.findall(r"(--[\w-]+)\s*:", foundation + product_css))
bare_refs = set(re.findall(r"var\(\s*(--[\w-]+)\s*\)", product_css))
missing_refs = sorted(bare_refs - defined - {"--wave", "--at", "--length", "--start"})
assert not missing_refs, f"产品介绍引用未定义 token：{missing_refs}"

print(
    f"product site: v{expected_content_version}, nine sections, "
    f"{len(html_keys)} bilingual keys, fictional demo and tokens passed"
)
