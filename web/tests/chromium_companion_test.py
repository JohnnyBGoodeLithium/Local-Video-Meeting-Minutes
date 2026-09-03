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
                    "url": f"{BASE}/companion#pair={pairing['token']}"})
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
                assert cdp.evaluate("location.search==='' && location.hash.startsWith('#pair=')"), \
                    "pairing token must arrive via URL fragment, never the query string"
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
                try:
                    wait(cdp, "!document.querySelector('#home-view').hidden && document.querySelectorAll('#recent .row').length", "connected home")
                except RuntimeError as exc:
                    pair_state = cdp.evaluate("document.querySelector('#pair-state')?.textContent")
                    offline_text = cdp.evaluate("document.querySelector('#offline')?.textContent")
                    home_hidden = cdp.evaluate("document.querySelector('#home-view')?.hidden")
                    rows = cdp.evaluate("document.querySelectorAll('#recent .row').length")
                    raise RuntimeError(f"{exc}; location={cdp.evaluate('location.href')!r}; "
                                       f"pairState={pair_state!r}; offline={offline_text!r}; "
                                       f"homeHidden={home_hidden!r}; rows={rows!r}; "
                                       f"errors={cdp.evaluate('window.__companionErrors')!r}") from exc
                assert cdp.evaluate("document.documentElement.scrollWidth<=innerWidth")
                assert pairing["token"] not in cdp.evaluate("location.href"), \
                    "pairing token must be cleared from the address bar after connect"
                screenshot(cdp, "companion-390-zh.png")

                cdp.evaluate("document.querySelector('#send-link-open').click();document.querySelector('#url').value='https://example.test/synthetic';document.querySelector('#link-form').requestSubmit()")
                wait(cdp, "!document.querySelector('#job-view').hidden", "send URL and job status")
                cdp.evaluate("document.querySelector('[data-back]').click();document.querySelector('#refresh').click()")
                wait(cdp, "document.querySelectorAll('#recent .row').length", "recent")
                wait(cdp, "sessionStorage.getItem('companion:job-pointer:v1')===null",
                     "URL import job reached a terminal state")
                cdp.evaluate("(()=>{const f=new File([new Blob([new Uint8Array(2*1024*1024)],{type:'audio/wav'})],'synthetic-upload.wav',{type:'audio/wav'});const dt=new DataTransfer();dt.items.add(f);const input=document.querySelector('#file');input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}))})()")
                wait(cdp, "!document.querySelector('#upload-progress').hidden && document.querySelector('#upload-label').textContent.includes('%')", "upload progress UI")
                wait(cdp, "!document.querySelector('#job-view').hidden", "upload created a job")
                wait(cdp, "sessionStorage.getItem('companion:job-pointer:v1')!==null",
                     "active job leaves a sessionStorage recovery pointer")
                pointer_id = cdp.evaluate("JSON.parse(sessionStorage.getItem('companion:job-pointer:v1')).id")
                assert pointer_id, "active job must leave a sessionStorage recovery pointer"
                cdp.evaluate(f"sessionStorage.setItem('companion:job-pointer:v1',JSON.stringify({{id:{json.dumps(pointer_id)},title:'synthetic'}}))")
                cdp.call("Page.navigate", {"url": f"{BASE}/companion"})
                wait(cdp, "document.readyState==='complete' && performance.getEntriesByType('resource')"
                          f".some(x=>x.name.includes('/api/companion/jobs/{pointer_id}'))",
                     "refresh re-queries the tracked job from the API")
                wait(cdp, "sessionStorage.getItem('companion:job-pointer:v1')===null",
                     "tracked job reached a terminal state")
                cdp.evaluate("if(!document.querySelector('#job-view').hidden)document.querySelector('#job-view [data-back]').click()")
                wait(cdp, "!document.querySelector('#home-view').hidden && document.querySelectorAll('#recent .row').length", "home after refresh recovery")
                cdp.evaluate("document.querySelector('#recent .row').click()")
                wait(cdp, "!document.querySelector('#item-view').hidden && document.querySelectorAll('#people button').length", "open meeting")
                cdp.evaluate("document.querySelector('#evidence .row')?.click()")
                wait(cdp, "performance.getEntriesByType('resource').some(x=>x.name.includes('/media/audio'))", "evidence request")
                cdp.evaluate("document.querySelector('#people button').click()")
                wait(cdp, "!document.querySelector('#person-view').hidden && !document.querySelector('#speaker-correction').hidden", "person focus")
                cdp.evaluate("document.querySelector('#preview-speaker').click()")
                wait(cdp, "!document.querySelector('#speaker-preview').hidden", "speaker preview")
                original_person = cdp.evaluate("document.querySelector('#person-name').textContent")
                target_person = cdp.evaluate("document.querySelector('#candidate').value")
                cdp.evaluate("document.querySelector('#confirm-speaker').click()")
                wait(cdp, f"document.querySelector('#person-name').textContent==={json.dumps(target_person)}",
                     "speaker confirm applied through the existing correction service")
                cdp.evaluate("document.querySelector('#undo-speaker').click()")
                wait(cdp, "!document.querySelector('#item-view').hidden", "speaker undo returned to the meeting")
                wait(cdp, f"[...document.querySelectorAll('#people button')].some(b=>b.textContent.startsWith({json.dumps(original_person)}))",
                     "undo restored the original person projection")
                cdp.evaluate("document.querySelector('#language').click()")
                assert cdp.evaluate("document.documentElement.lang==='en' && document.querySelectorAll('button:not([disabled])').length>5")
                screenshot(cdp, "companion-390-en.png")

                sessions = http("/api/companion/admin/sessions")["sessions"]
                http(f"/api/companion/admin/sessions/{sessions[0]['id']}/revoke", "POST", {})
                cdp.evaluate("document.querySelector('#refresh').click()")
                wait(cdp, "!document.querySelector('#offline').hidden && document.querySelector('#offline').textContent.includes('revoked')", "revoked session")
                assert cdp.evaluate("sessionStorage.getItem('companion:job-pointer:v1')===null"), \
                    "revoke must clear the local job recovery pointer"
                cdp.evaluate("document.querySelector('#retry').click()")
                wait(cdp, "!document.querySelector('#offline').hidden", "retry keeps the revoked offline state")
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
    print("companion browser: pairing, URL, upload progress, status, review, evidence, person, "
          "speaker confirm/undo, refresh recovery, revoke, bilingual and 390px passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
