#!/usr/bin/env python3
"""Capture the temporary product-site art direction study with real Chromium.

The study contains only fictional data and only the Hero and Verify sections. It is
kept separate from the formal product page while PR #9 is under visual review.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import json
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from chromium_speaker_correction_test import CDP, wait_devtools_port


ROOT = Path(__file__).resolve().parents[2]
STUDY_DIR = ROOT / "artifacts" / "product-site-directions"
OUTPUT_DIR = STUDY_DIR / "screenshots"
CHROME = (
    shutil.which("google-chrome")
    or shutil.which("chromium")
    or shutil.which("chromium-browser")
)
DIRECTIONS = ("splice", "dossier", "cue")
LANGUAGES = (("zh-CN", "zh"), ("en", "en"))
VIEWPORTS = ((1440, 1000), (390, 844))


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


def page_target(port: int, timeout: float = 10) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/list", timeout=2,
            ) as response:
                targets = json.load(response)
            target = next(
                (item for item in targets if item.get("type") == "page"), None,
            )
            if target:
                return target
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(0.05)
    raise RuntimeError("No Chromium page target became available")


def wait_for_study(cdp: CDP, timeout: float = 12) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ready = cdp.evaluate(
                "document.documentElement.dataset.ready === 'true' "
                "&& document.readyState === 'complete'"
            )
            if ready:
                cdp.evaluate("document.fonts.ready")
                return
        except RuntimeError as exc:
            if "Execution context was destroyed" not in str(exc):
                raise
        time.sleep(0.05)
    raise RuntimeError("Art direction study did not finish loading")


def inspect_page(cdp: CDP, direction: str, language: str, width: int) -> dict:
    result = cdp.evaluate(
        """
(() => {
  const root = document.documentElement;
  const body = document.body;
  const sections = [...document.querySelectorAll('main > section')]
    .map(section => section.id);
  const instrument = document.querySelector('.review-instrument');
  const signature = document.querySelector('.evidence-needle, .evidence-label');
  return {
    ready: root.dataset.ready,
    direction: root.dataset.direction,
    language: root.lang,
    sections,
    innerWidth: window.innerWidth,
    clientWidth: root.clientWidth,
    scrollWidth: root.scrollWidth,
    scrollHeight: Math.ceil(Math.max(root.scrollHeight, body.scrollHeight)),
    stylesheetCount: document.styleSheets.length,
    bodyBackground: getComputedStyle(body).backgroundColor,
    instrumentDisplay: instrument ? getComputedStyle(instrument).display : null,
    signatureVisible: !!signature && getComputedStyle(signature).display !== 'none',
    errors: window.__directionStudyErrors || [],
  };
})()
        """
    )
    expected_sections = ["hero", "verify"]
    if result.get("ready") != "true":
        raise AssertionError(f"study not ready: {result}")
    if result.get("direction") != direction or result.get("language") != language:
        raise AssertionError(f"study route mismatch: {result}")
    if result.get("sections") != expected_sections:
        raise AssertionError(f"expected only Hero and Verify: {result}")
    if result.get("innerWidth") != width:
        raise AssertionError(f"viewport width mismatch: {result}")
    if result.get("scrollWidth", 0) > result.get("clientWidth", 0):
        raise AssertionError(f"horizontal overflow: {result}")
    if result.get("stylesheetCount", 0) < 1:
        raise AssertionError(f"direction stylesheet did not load: {result}")
    if result.get("bodyBackground") in ("rgba(0, 0, 0, 0)", "transparent"):
        raise AssertionError(f"direction background did not render: {result}")
    if result.get("instrumentDisplay") in (None, "none"):
        raise AssertionError(f"review instrument did not render: {result}")
    if not result.get("signatureVisible"):
        raise AssertionError(f"product signature did not render: {result}")
    if result.get("errors"):
        raise AssertionError(f"browser errors: {result['errors']}")
    return result


def capture(cdp: CDP, path: Path, scroll_height: int, width: int) -> None:
    screenshot = cdp.call(
        "Page.captureScreenshot",
        {
            "format": "png",
            "fromSurface": True,
            "captureBeyondViewport": True,
            "clip": {
                "x": 0,
                "y": 0,
                "width": width,
                "height": scroll_height,
                "scale": 1,
            },
        },
    )
    path.write_bytes(base64.b64decode(screenshot["data"]))


def main() -> int:
    if not CHROME:
        raise RuntimeError("Chromium is required for product direction screenshots")
    if not (STUDY_DIR / "explore.html").is_file():
        raise RuntimeError(f"Missing direction study: {STUDY_DIR / 'explore.html'}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in (*OUTPUT_DIR.glob("*.png"), OUTPUT_DIR / "manifest.json"):
        if stale.exists():
            stale.unlink()

    handler = functools.partial(QuietHandler, directory=str(STUDY_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    variants: list[dict] = []
    try:
        with tempfile.TemporaryDirectory(
            prefix="product-direction-chromium-", ignore_cleanup_errors=True,
        ) as temp_dir:
            profile = Path(temp_dir)
            process = subprocess.Popen(
                [
                    CHROME,
                    "--headless=new",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    "--no-sandbox",
                    "--remote-debugging-port=0",
                    "--remote-allow-origins=*",
                    f"--user-data-dir={profile}",
                    "--window-size=1440,1000",
                    "about:blank",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                port = wait_devtools_port(profile / "DevToolsActivePort")
                target = page_target(port)
                cdp = CDP(target["webSocketDebuggerUrl"])
                try:
                    cdp.call("Page.enable")
                    cdp.call("Runtime.enable")
                    cdp.call(
                        "Page.addScriptToEvaluateOnNewDocument",
                        {
                            "source": """
window.__directionStudyErrors = [];
window.addEventListener('error', event => {
  window.__directionStudyErrors.push(String(event.error || event.message));
});
window.addEventListener('unhandledrejection', event => {
  window.__directionStudyErrors.push(String(event.reason));
});
                            """,
                        },
                    )
                    for direction in DIRECTIONS:
                        for language, language_slug in LANGUAGES:
                            for width, height in VIEWPORTS:
                                cdp.call(
                                    "Emulation.setDeviceMetricsOverride",
                                    {
                                        "width": width,
                                        "height": height,
                                        "deviceScaleFactor": 1,
                                        "mobile": width < 600,
                                    },
                                )
                                url = (
                                    f"{base_url}/explore.html?"
                                    f"direction={direction}&lang={language}"
                                )
                                cdp.call("Page.navigate", {"url": url})
                                wait_for_study(cdp)
                                metrics = inspect_page(
                                    cdp, direction, language, width,
                                )
                                filename = (
                                    f"{direction}-{language_slug}-{width}.png"
                                )
                                destination = OUTPUT_DIR / filename
                                capture(
                                    cdp,
                                    destination,
                                    metrics["scrollHeight"],
                                    width,
                                )
                                content = destination.read_bytes()
                                variants.append(
                                    {
                                        "filename": filename,
                                        "direction": direction,
                                        "language": language,
                                        "viewport": {
                                            "width": width,
                                            "height": height,
                                        },
                                        "page_height": metrics["scrollHeight"],
                                        "bytes": len(content),
                                        "sha256": hashlib.sha256(content).hexdigest(),
                                    }
                                )
                finally:
                    cdp.close()
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)

    manifest = {
        "schema": "product-direction-study/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fictional_data": True,
        "formal_product_files_modified": False,
        "variants": variants,
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if len(variants) != 12:
        raise AssertionError(f"expected 12 screenshots, got {len(variants)}")
    print("product direction screenshots: 12 passed, 0 failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
