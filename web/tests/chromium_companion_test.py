#!/usr/bin/env python3
"""Synthetic 390px Companion journey through real Chromium and the isolated server."""

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
BASE = os.environ.get("MM_TEST_BASE", "http://127.0.0.1:8899")


def http(path: str, method: str = "GET", payload: dict | None = None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(BASE + path, data=body, method=method,
                                     headers={"Content-Type": "application/json", "Origin": BASE})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def wait(cdp: CDP, expression: str, label: str, timeout: float = 12):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            value = cdp.evaluate(expression)
            if value:
                return value
        except RuntimeError as exc:
            if "Execution context was destroyed" not in str(exc):
                raise
        time.sleep(.1)
    raise RuntimeError(f"timeout: {label}")


def screenshot(cdp: CDP, name: str) -> None:
    output = os.environ.get("MM_COMPANION_SCREENSHOT_DIR")
    if not output:
        return
    path = Path(output)
    path.mkdir(parents=True, exist_ok=True)
    data = cdp.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
    (path / name).write_bytes(base64.b64decode(data["data"]))


def main() -> int:
    if not CHROME:
        print("companion browser: chromium not found, skipped")
        return 0
    pairing = http("/api/companion/admin/pairings", "POST", {})
    with tempfile.TemporaryDirectory(prefix="mm-chromium-companion-",
                                     ignore_cleanup_errors=True) as tmp:
        profile = Path(tmp)
        process = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--remote-debugging-port=0", "--remote-allow-origins=*",
            f"--user-data-dir={profile}", "--window-size=390,844",
            "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            port = wait_devtools_port(profile / "DevToolsActivePort")
            target = None
            for _ in range(100):
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list") as response:
                    target = next((row for row in json.load(response)
                                   if row.get("type") == "page"
                                   and str(row.get("url") or "") == "about:blank"), None)
                if target:
                    break
                time.sleep(.05)
            if not target:
                raise RuntimeError("No Chromium page target")
            cdp = CDP(target["webSocketDebuggerUrl"])
            try:
                cdp.call("Page.enable")
                cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": (
                    "window.__companionErrors=[];"
                    "addEventListener('error',e=>__companionErrors.push({message:e.message,"
                    "source:e.filename,line:e.lineno}));"
                    "addEventListener('unhandledrejection',e=>__companionErrors.push({"
                    "message:String(e.reason)}));")})
                cdp.call("Page.navigate", {
                    "url": f"{BASE}/companion?pair={pairing['token']}"})
                try:
                    wait(cdp, "document.readyState==='complete' && document.querySelector('#pair-view') && !document.querySelector('#pair-view').hidden",
                         "pairing screen")
                except RuntimeError as exc:
                    location = cdp.evaluate("location.href")
                    state = cdp.evaluate("document.body?.innerText?.slice(0,500)")
                    errors = cdp.evaluate("window.__companionErrors")
                    scripts = cdp.evaluate("[...document.scripts].map(x=>x.src)")
                    raise RuntimeError(f"{exc}; location={location!r}; body={state!r}; "
                                       f"errors={errors!r}; scripts={scripts!r}") from exc
                cdp.evaluate("document.querySelector('#connect').click()")
                request = None
                for _ in range(80):
                    rows = http("/api/companion/admin/requests")["requests"]
                    request = rows[0] if rows else None
                    if request:
                        break
                    time.sleep(.1)
                if not request:
                    raise RuntimeError("pairing request missing")
                http("/api/companion/admin/decide", "POST",
                     {"request_id": request["request_id"], "allow": True})
                wait(cdp, "!document.querySelector('#home-view').hidden && document.querySelectorAll('#recent .row').length", "connected home")
                assert cdp.evaluate("document.documentElement.scrollWidth<=innerWidth")
                screenshot(cdp, "companion-390-zh.png")

                cdp.evaluate("document.querySelector('#send-link-open').click();document.querySelector('#url').value='https://example.test/synthetic';document.querySelector('#link-form').requestSubmit()")
                wait(cdp, "!document.querySelector('#job-view').hidden", "send URL and job status")
                cdp.evaluate("document.querySelector('[data-back]').click();document.querySelector('#refresh').click()")
                wait(cdp, "document.querySelectorAll('#recent .row').length", "recent")
                cdp.evaluate("document.querySelector('#recent .row').click()")
                wait(cdp, "!document.querySelector('#item-view').hidden && document.querySelectorAll('#people button').length", "open meeting")
                cdp.evaluate("document.querySelector('#evidence .row')?.click()")
                wait(cdp, "performance.getEntriesByType('resource').some(x=>x.name.includes('/media/audio'))", "evidence request")
                cdp.evaluate("document.querySelector('#people button').click()")
                wait(cdp, "!document.querySelector('#person-view').hidden && !document.querySelector('#speaker-correction').hidden", "person focus")
                cdp.evaluate("document.querySelector('#preview-speaker').click()")
                wait(cdp, "!document.querySelector('#speaker-preview').hidden", "speaker preview")
                cdp.evaluate("document.querySelector('#language').click()")
                assert cdp.evaluate("document.documentElement.lang==='en' && document.querySelectorAll('button:not([disabled])').length>5")
                screenshot(cdp, "companion-390-en.png")

                sessions = http("/api/companion/admin/sessions")["sessions"]
                http(f"/api/companion/admin/sessions/{sessions[0]['id']}/revoke", "POST", {})
                cdp.evaluate("document.querySelector('#refresh').click()")
                wait(cdp, "!document.querySelector('#offline').hidden && document.querySelector('#offline').textContent.includes('revoked')", "revoked session")
                final = cdp.evaluate("({errors:window.__companionErrors,scrollWidth:document.documentElement.scrollWidth,innerWidth})")
                assert final["errors"] == [] and final["scrollWidth"] <= final["innerWidth"], final
            finally:
                cdp.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    print("companion browser: pairing, URL, status, review, evidence, person, revoke, bilingual and 390px passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
