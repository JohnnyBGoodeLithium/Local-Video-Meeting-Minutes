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
    set_viewport(cdp, 1440, 1000)
    set_language(cdp, "zh-CN")
    time.sleep(0.5)
    capture(cdp, output / "hero-zh-1440.png")
    capture(cdp, output / "full-zh-1440.png", full=True)
    capture(cdp, output / "hero-meeting.png", selector=".product-demo")

    cdp.evaluate('document.querySelector(\'[data-demo-mode="video"]\').click()')
    time.sleep(0.25)
    capture(cdp, output / "hero-video.png", selector=".product-demo")
    cdp.evaluate('document.querySelector(\'[data-demo-mode="meeting"]\').click()')

    set_language(cdp, "en")
    cdp.evaluate("scrollTo(0, 0)")
    capture(cdp, output / "hero-en-1440.png")
    capture(cdp, output / "full-en-1440.png", full=True)

    for width, height in ((1024, 900), (390, 844)):
        set_viewport(cdp, width, height)
        set_language(cdp, "zh-CN")
        capture(cdp, output / f"full-zh-{width}.png", full=True)
        set_language(cdp, "en")
        capture(cdp, output / f"full-en-{width}.png", full=True)

    set_viewport(cdp, 1440, 1000)
    set_language(cdp, "zh-CN")
    cdp.evaluate("document.querySelector('[data-verify-toggle]').click()")
    capture(cdp, output / "verify-evidence.png", selector=".evidence-workbench")


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
                assert baseline["maturity"] == [
                    "validated", "working", "early", "experimental", "implemented",
                ]
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
                assert english["title"].startswith("Meeting Context |")
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

                for width, height in ((768, 900), (390, 844)):
                    set_viewport(cdp, width, height)
                    metric = cdp.evaluate(r"""
({clientWidth: document.documentElement.clientWidth,
  scrollWidth: document.documentElement.scrollWidth,
  headerNav: getComputedStyle(document.querySelector('.product-nav')).display,
  meetingVisible: !document.querySelector('[data-demo-panel="meeting"]').hidden})
""")
                    assert metric["scrollWidth"] <= metric["clientWidth"], (width, metric)
                    assert metric["headerNav"] == "none", (width, metric)
                    assert metric["meetingVisible"], (width, metric)

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
