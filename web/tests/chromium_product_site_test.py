#!/usr/bin/env python3
"""Exercise and optionally capture the public product site through Chromium CDP.

The page and screenshots use only the hard-coded fictional Northstar demonstration.
No meeting, recording, job, speaker-bank, or private report path is read by this test.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from chromium_speaker_correction_test import CDP, wait_devtools_port


CHROME = (shutil.which("chromium") or shutil.which("chromium-browser")
          or shutil.which("google-chrome"))


def wait_for_page(cdp: CDP, expression: str, label: str, timeout: float = 12) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if cdp.evaluate(expression):
                return
        except RuntimeError as exc:
            if "Execution context was destroyed" not in str(exc):
                raise
        time.sleep(0.08)
    raise RuntimeError(f"Product site timeout: {label}")


def set_viewport(cdp: CDP, width: int, height: int) -> None:
    cdp.call("Emulation.setDeviceMetricsOverride", {
        "width": width, "height": height, "deviceScaleFactor": 1,
        "mobile": width <= 520,
    })
    cdp.evaluate("scrollTo(0, 0)")
    time.sleep(0.12)


def capture(cdp: CDP, path: Path, *, full: bool = False, selector: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    params: dict[str, object] = {"format": "png", "fromSurface": True}
    if selector:
        rect = cdp.evaluate(f"""
(() => {{
  const rect = document.querySelector({json.dumps(selector)}).getBoundingClientRect();
  return {{x: rect.left + scrollX, y: rect.top + scrollY,
    width: rect.width, height: rect.height}};
}})()
""")
        params.update({"captureBeyondViewport": True, "clip": {**rect, "scale": 1}})
    elif full:
        size = cdp.call("Page.getLayoutMetrics")["cssContentSize"]
        params.update({"captureBeyondViewport": True, "clip": {
            "x": 0, "y": 0, "width": size["width"], "height": size["height"], "scale": 1,
        }})
    else:
        params["captureBeyondViewport"] = False
    result = cdp.call("Page.captureScreenshot", params)
    path.write_bytes(base64.b64decode(result["data"]))


def set_language(cdp: CDP, language: str) -> None:
    cdp.evaluate(
        f'document.querySelector(\'[data-ui-language="{language}"]\').click()'
    )
    wait_for_page(cdp, f"document.documentElement.lang === {json.dumps(language)}", language)
    time.sleep(0.08)


def create_screenshots(cdp: CDP, output: Path) -> None:
    for width, height, filename in (
        (393, 852, "review-surfaces-393-zh.png"),
        (820, 1180, "review-surfaces-820-zh.png"),
        (1440, 900, "review-surfaces-1440-zh.png"),
        (1920, 1080, "review-surfaces-1920-zh.png"),
        (2560, 1440, "review-surfaces-2560-zh.png"),
    ):
        set_viewport(cdp, width, height)
        set_language(cdp, "zh-CN")
        capture(
            cdp, output / filename,
            selector="#review-anywhere",
        )

    for width, height, filename in (
        (1440, 900, "review-surfaces-1440-en.png"),
        (1920, 1080, "review-surfaces-1920-en.png"),
    ):
        set_viewport(cdp, width, height)
        set_language(cdp, "en")
        capture(
            cdp, output / filename,
            selector="#review-anywhere",
        )

    for width, height, filename in (
        (393, 852, "closing-cta-393-zh.png"),
        (1920, 1080, "closing-cta-1920-zh.png"),
        (2560, 1440, "closing-cta-2560-zh.png"),
    ):
        set_viewport(cdp, width, height)
        set_language(cdp, "zh-CN")
        capture(cdp, output / filename, selector=".final-cta")

    set_viewport(cdp, 1920, 1080)
    set_language(cdp, "en")
    capture(cdp, output / "closing-cta-1920-en.png", selector=".final-cta")


def main() -> int:
    if not CHROME:
        print("product site browser: chromium not found, skipped")
        return 0
    base = os.environ.get("MM_TEST_BASE", "http://127.0.0.1:8899")
    screenshot_dir = os.environ.get("MM_PRODUCT_SCREENSHOT_DIR", "").strip()
    with tempfile.TemporaryDirectory(
        prefix="mm-chromium-product-site-", ignore_cleanup_errors=True,
    ) as tmp:
        profile = Path(tmp)
        process = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--remote-debugging-port=0", "--remote-allow-origins=*",
            f"--user-data-dir={profile}", "--window-size=1440,1000", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            port = wait_devtools_port(profile / "DevToolsActivePort")
            target = None
            deadline = time.time() + 10
            while time.time() < deadline:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list") as response:
                    pages = json.load(response)
                target = next((item for item in pages if item.get("type") == "page"), None)
                if target:
                    break
                time.sleep(0.05)
            if not target:
                raise RuntimeError("No Chromium page target")
            cdp = CDP(target["webSocketDebuggerUrl"])
            try:
                cdp.call("Page.enable")
                cdp.call("Runtime.enable")
                cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": r"""
window.__productErrors = [];
window.__productFetches = [];
addEventListener('error', event => window.__productErrors.push(String(event.message)));
addEventListener('unhandledrejection', event =>
  window.__productErrors.push(String(event.reason?.message || event.reason)));
const originalFetch = window.fetch.bind(window);
window.fetch = (input, init) => {
  window.__productFetches.push(String(input));
  return originalFetch(input, init);
};
"""})
                cdp.call("Page.navigate", {"url": f"{base}/product"})
                wait_for_page(
                    cdp,
                    "document.readyState === 'complete' && "
                    "document.documentElement.dataset.productReady === 'true'",
                    "module initialization",
                )
                time.sleep(0.5)

                baseline = cdp.evaluate(r"""
(() => ({
  sections: [...document.querySelectorAll('[data-product-section]')].map(node => node.id),
  meetingVisible: !document.querySelector('[data-demo-panel="meeting"]').hidden,
  videoHidden: document.querySelector('[data-demo-panel="video"]').hidden,
  selectedMode: document.querySelector('[data-demo-mode][aria-selected="true"]').dataset.demoMode,
                  maturity: [...document.querySelectorAll('[data-maturity]')].map(node => node.dataset.maturity),
                  surfaces: [...document.querySelectorAll('[data-review-surface]')].map(node => node.dataset.reviewSurface),
                  continuation: [...document.querySelectorAll('[data-continuation-layer]')].map(node => node.dataset.continuationLayer),
                  capabilities: [...document.querySelectorAll('.companion-capabilities dt')].map(node => node.textContent),
  fictional: document.body.textContent.includes('虚构演示数据'),
  fetches: window.__productFetches,
  errors: window.__productErrors,
}))()
""")
                assert baseline["sections"] == [
                    "overview", "meeting-video", "find", "verify", "correct",
                    "review-anywhere", "playback", "live", "reuse",
                ]
                assert baseline["meetingVisible"] and baseline["videoHidden"]
                assert baseline["selectedMode"] == "meeting"
                assert baseline["maturity"] == ["experimental", "implemented"]
                assert baseline["surfaces"] == ["workbench", "companion", "meetingpack"]
                assert baseline["continuation"] == ["minutes", "knowledge"]
                assert baseline["capabilities"] == ["发送", "跟进", "回顾", "核对"]
                assert baseline["fictional"]
                assert baseline["fetches"] == ["/api/health"], baseline["fetches"]
                assert not baseline["errors"], baseline["errors"]

                video = cdp.evaluate(r"""
(() => {
  document.querySelector('[data-demo-mode="video"]').click();
  document.querySelector('[data-demo-panel="video"] [data-demo-choice="materials"]').click();
  return {
    meetingHidden: document.querySelector('[data-demo-panel="meeting"]').hidden,
    videoVisible: !document.querySelector('[data-demo-panel="video"]').hidden,
    topic: document.querySelector('[data-demo-panel="video"] [data-demo-bind="selection"]').textContent,
    range: document.querySelector('[data-demo-panel="video"] [data-demo-bind="range"]').textContent,
  };
})()
""")
                assert video == {
                    "meetingHidden": True, "videoVisible": True,
                    "topic": "材料与结构", "range": "05:48–07:02",
                }

                evidence = cdp.evaluate(r"""
(() => {
  document.querySelector('[data-demo-mode="meeting"]').click();
  const button = document.querySelector('[data-demo-panel="meeting"] [data-demo-evidence]');
  button.click();
  return {expanded: button.getAttribute('aria-expanded'),
    hidden: button.parentElement.querySelector('[data-demo-evidence-detail]').hidden};
})()
""")
                assert evidence == {"expanded": "true", "hidden": False}

                before_maturity = baseline["maturity"]
                set_language(cdp, "en")
                english = cdp.evaluate(r"""
({
  title: document.title,
  description: document.querySelector('meta[name="description"]').content,
  hero: document.querySelector('[data-i18n="heroTitle"]').textContent,
  demo: document.querySelector('[data-demo-panel="meeting"] [data-demo-bind="conclusion"]').textContent,
  maturity: [...document.querySelectorAll('[data-maturity]')].map(node => node.dataset.maturity),
  errors: window.__productErrors,
})
""")
                assert english["title"].startswith("Local Video Meeting Minutes |")
                assert english["description"].startswith("Review meetings and product videos")
                assert english["hero"].startswith("A two-hour meeting")
                assert "supplier validation" in english["demo"].lower()
                assert english["maturity"] == before_maturity
                assert not english["errors"], english["errors"]

                cdp.call("Emulation.setEmulatedMedia", {"features": [{
                    "name": "prefers-reduced-motion", "value": "reduce",
                }]})
                reduced = cdp.evaluate(r"""
({hero: getComputedStyle(document.querySelector('.hero-copy')).animationDuration,
  demo: getComputedStyle(document.querySelector('.product-demo')).animationDuration,
  timeline: getComputedStyle(document.querySelector('.timeline > i')).transitionDuration})
""")
                reduced_seconds = {
                    key: float(value.removesuffix("s")) for key, value in reduced.items()
                }
                assert all(value <= 0.001 for value in reduced_seconds.values()), reduced

                viewport_matrix = (
                    (393, 852), (430, 932), (820, 1180), (1180, 820),
                    (1440, 900), (1920, 1080), (2560, 1440),
                )
                for language in ("zh-CN", "en"):
                    set_language(cdp, language)
                    for width, height in viewport_matrix:
                        set_viewport(cdp, width, height)
                        metric = cdp.evaluate(r"""
(() => {
  const viewport = document.documentElement.clientWidth;
  const checked = [...document.querySelectorAll(
    '[data-product-section], .review-card, .companion-capabilities, ' +
    '.final-cta-content, .final-actions a'
  )];
  const overflow = checked.map(node => {
    const rect = node.getBoundingClientRect();
    return {name: node.id || node.className, left: rect.left, right: rect.right};
  }).filter(rect => rect.left < -1 || rect.right > viewport + 1);
  const content = document.querySelector('.final-cta-content');
  const contentRect = content.getBoundingClientRect();
  const rail = getComputedStyle(content, '::before');
  const railRect = {
    left: contentRect.left + parseFloat(rail.left),
    top: contentRect.top + parseFloat(rail.top),
    right: contentRect.left + parseFloat(rail.left) + parseFloat(rail.width),
    bottom: contentRect.top + parseFloat(rail.top) + parseFloat(rail.height),
  };
  const railInside = railRect.left >= contentRect.left - 1 &&
    railRect.right <= contentRect.right + 1 &&
    railRect.top >= contentRect.top - 1 &&
    railRect.bottom <= contentRect.bottom + 1;
  const capabilityVisible = [...document.querySelectorAll('.companion-capabilities div')]
    .filter(node => {
      const rect = node.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && getComputedStyle(node).visibility !== 'hidden';
    }).length;
  const statusOverlap = [...document.querySelectorAll('.review-card')].some(card => {
    const status = card.querySelector('.status-badge');
    const body = card.querySelector('.review-body');
    if (!status || !body) return false;
    const a = status.getBoundingClientRect();
    const b = body.getBoundingClientRect();
    return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
  });
  const lineTexts = element => {
    const text = [...element.textContent];
    const lines = new Map();
    text.forEach((character, index) => {
      const range = document.createRange();
      range.setStart(element.firstChild, index);
      range.setEnd(element.firstChild, index + 1);
      const rect = range.getBoundingClientRect();
      const key = Math.round(rect.top);
      lines.set(key, (lines.get(key) || '') + character);
    });
    return [...lines.values()].map(line => line.trim()).filter(Boolean);
  };
  const closingLines = lineTexts(document.querySelector('.final-cta h2'));
  const orphanLine = closingLines.some(line =>
    line.length === 1 && /[\u3000-\u303f\u3400-\u9fff]/u.test(line)
  );
  return {
    clientWidth: viewport,
    scrollWidth: document.documentElement.scrollWidth,
    overflow,
    railInside,
    capabilityVisible,
    statusOverlap,
    closingLines,
    orphanLine,
    headerNav: getComputedStyle(document.querySelector('.product-nav')).display,
  };
})()
""")
                        assert metric["scrollWidth"] <= metric["clientWidth"], (
                            language, width, metric,
                        )
                        assert not metric["overflow"], (language, width, metric["overflow"])
                        assert metric["railInside"], (language, width, metric)
                        assert metric["capabilityVisible"] == 4, (language, width, metric)
                        assert not metric["statusOverlap"], (language, width, metric)
                        if width >= 1440:
                            assert not metric["orphanLine"], (language, width, metric["closingLines"])
                        assert metric["headerNav"] == ("none" if width <= 768 else "flex"), (
                            language, width, metric,
                        )

                interaction = cdp.evaluate(r"""
(() => {
  const primary = document.querySelector('.final-primary');
  const secondary = document.querySelector('.final-actions a:last-child');
  primary.focus();
  const primaryFocused = document.activeElement === primary;
  secondary.focus();
  return {
    primaryHref: primary.getAttribute('href'),
    secondaryHref: secondary.getAttribute('href'),
    primaryFocused,
    secondaryFocused: document.activeElement === secondary,
    anchorsResolve: [...document.querySelectorAll('a[href^="#"]')].every(
      link => document.querySelector(link.getAttribute('href'))
    ),
  };
})()
""")
                assert interaction == {
                    "primaryHref": "/",
                    "secondaryHref": "#find",
                    "primaryFocused": True,
                    "secondaryFocused": True,
                    "anchorsResolve": True,
                }

                if screenshot_dir:
                    cdp.call("Emulation.setEmulatedMedia", {"features": []})
                    create_screenshots(cdp, Path(screenshot_dir))
            finally:
                cdp.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    print("product site browser: bilingual journey, evidence, responsive and reduced motion passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
