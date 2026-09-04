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


def viewport(cdp: CDP, width: int, height: int) -> None:
    cdp.call("Emulation.setDeviceMetricsOverride", {
        "width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600,
    })
    time.sleep(.2)


def main() -> int:
    if not CHROME:
        print("companion browser: chromium not found, skipped")
        return 0
    generated_video = None
    test_root = os.environ.get("MM_TEST_ROOT")
    if test_root and shutil.which("ffmpeg"):
        candidate = Path(test_root) / "meetings" / "_smoke" / "source_video.mp4"
        if not candidate.exists():
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=0x172033:s=640x360:d=10",
                "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-shortest",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(candidate),
            ], check=True)
            generated_video = candidate
    pairing = http("/api/companion/admin/pairings", "POST", {})
    with tempfile.TemporaryDirectory(prefix="mm-chromium-companion-",
                                     ignore_cleanup_errors=True) as tmp:
        profile = Path(tmp)
        process = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--remote-debugging-port=0", "--remote-allow-origins=*",
            f"--user-data-dir={profile}", "--window-size=393,852",
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
                screenshot(cdp, "phone-home-393.png")

                cdp.evaluate("document.querySelector('#send-open').click()")
                screenshot(cdp, "phone-send-sheet-393.png")
                cdp.evaluate("document.querySelector('#url').value='https://example.test/synthetic';document.querySelector('#link-form').requestSubmit()")
                wait(cdp, "!document.querySelector('#home-view').hidden", "send URL returns home")
                wait(cdp, "document.querySelector('#processing-list .row')!==null", "processing card")
                screenshot(cdp, "phone-processing-393.png")
                time.sleep(3)
                assert cdp.evaluate("!document.querySelector('#home-view').hidden"), \
                    "background polling must not navigate away from Home"
                if cdp.evaluate("document.querySelector('#processing-list .row')!==null"):
                    cdp.evaluate("document.querySelector('#processing-list .row').click()")
                    wait(cdp, "!document.querySelector('#job-view').hidden", "open job manually")
                    cdp.call("Runtime.evaluate", {"expression": "history.back()"})
                    wait(cdp, "!document.querySelector('#home-view').hidden", "browser Back returns Home")
                cdp.evaluate("document.querySelector('#refresh').click()")
                wait(cdp, "document.querySelectorAll('#recent .row').length", "recent")
                wait(cdp, "JSON.parse(sessionStorage.getItem('companion:tracked-jobs:v2')||'[]').length===0",
                     "URL import job reached a terminal state")
                cdp.evaluate("(()=>{const f=new File([new Blob([new Uint8Array(2*1024*1024)],{type:'audio/wav'})],'synthetic-upload.wav',{type:'audio/wav'});const dt=new DataTransfer();dt.items.add(f);const input=document.querySelector('#file');input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}))})()")
                wait(cdp, "!document.querySelector('#upload-progress').hidden && document.querySelector('#upload-label').textContent.includes('%')", "upload progress UI")
                wait(cdp, "!document.querySelector('#home-view').hidden", "upload returns Home")
                wait(cdp, "JSON.parse(sessionStorage.getItem('companion:tracked-jobs:v2')||'[]').length>0",
                     "active job leaves a safe tracked-jobs record")
                pointer_id = cdp.evaluate("JSON.parse(sessionStorage.getItem('companion:tracked-jobs:v2'))[0].id")
                assert pointer_id, "active job must leave a sessionStorage recovery pointer"
                cdp.call("Page.navigate", {"url": f"{BASE}/companion"})
                wait(cdp, "document.readyState==='complete' && performance.getEntriesByType('resource')"
                          f".some(x=>x.name.includes('/api/companion/jobs/{pointer_id}'))",
                     "refresh re-queries the tracked job from the API")
                assert cdp.evaluate("!document.querySelector('#home-view').hidden"), \
                    "refresh with a running job must open Home"
                wait(cdp, "JSON.parse(sessionStorage.getItem('companion:tracked-jobs:v2')||'[]').length===0",
                     "tracked job reached a terminal state")
                wait(cdp, "!document.querySelector('#home-view').hidden && document.querySelectorAll('#recent .row').length", "home after refresh recovery")
                cdp.evaluate("document.querySelector('#recent .row').click()")
                wait(cdp, "!document.querySelector('#item-view').hidden && document.querySelectorAll('#people .row').length", "open meeting")
                assert cdp.evaluate("document.querySelectorAll('[role=tabpanel]:not([hidden])').length===1")
                assert cdp.evaluate("document.querySelectorAll('#recent .row').length<=5")
                screenshot(cdp, "phone-overview-393.png")
                cdp.evaluate("document.querySelector('#tab-chapters').click()")
                wait(cdp, "!document.querySelector('#panel-chapters').hidden && document.querySelectorAll('#chapters .row').length", "Chapters tab")
                screenshot(cdp, "phone-chapters-393.png")
                cdp.evaluate("document.querySelector('#tab-people').click()")
                wait(cdp, "!document.querySelector('#panel-people').hidden", "People tab")
                screenshot(cdp, "phone-people-393.png")
                cdp.evaluate("document.querySelector('#tab-transcript').click()")
                wait(cdp, "!document.querySelector('#panel-transcript').hidden && document.querySelectorAll('#transcript .transcript-turn').length", "Transcript tab")
                assert cdp.evaluate("document.querySelectorAll('#transcript .transcript-turn').length<=50")
                cdp.evaluate("document.querySelector('#transcript .transcript-turn button').click()")
                screenshot(cdp, "phone-transcript-player-393.png")
                cdp.evaluate("document.querySelector('#caption-mode').value='source';document.querySelector('#caption-mode').dispatchEvent(new Event('change',{bubbles:true}))")
                screenshot(cdp, "phone-video-caption-393.png")
                viewport(cdp, 820, 1180)
                cdp.evaluate("document.querySelector('#tab-overview').click()")
                wait(cdp, "!document.querySelector('#panel-overview').hidden && Boolean(document.querySelector('#conclusions .row'))", "overview conclusion after route reload")
                screenshot(cdp, "tablet-review-820.png")
                viewport(cdp, 1180, 820)
                screenshot(cdp, "tablet-landscape-1180.png")
                viewport(cdp, 1440, 900)
                screenshot(cdp, "laptop-review-1440.png")
                viewport(cdp, 393, 852)
                cdp.evaluate("document.querySelector('#conclusions .row')?.click()")
                wait(cdp, "performance.getEntriesByType('resource').some(x=>x.name.includes('/evidence/'))", "evidence lookup")
                assert cdp.evaluate("['audio','video'].some(kind=>document.querySelector(`#${kind}-player`).src.includes(`/media/${kind}`))"), \
                    "evidence playback must keep an approved audio or video source"
                cdp.evaluate("document.querySelector('#tab-people').click()")
                wait(cdp, "!document.querySelector('#panel-people').hidden", "People tab")
                cdp.evaluate("document.querySelector('#people .row').click()")
                wait(cdp, "!document.querySelector('#person-view').hidden && !document.querySelector('#speaker-correction').hidden", "person focus")
                cdp.evaluate("document.querySelector('#preview-speaker').click()")
                wait(cdp, "!document.querySelector('#speaker-preview').hidden", "speaker preview")
                screenshot(cdp, "phone-speaker-confirm-393.png")
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
                assert cdp.evaluate("[...document.querySelectorAll('[role=tab]')].every(x=>x.getAttribute('aria-selected')==='true'||x.getAttribute('aria-selected')==='false')")

                sessions = http("/api/companion/admin/sessions")["sessions"]
                http(f"/api/companion/admin/sessions/{sessions[0]['id']}/revoke", "POST", {})
                cdp.evaluate("document.querySelector('#refresh').click()")
                wait(cdp, "!document.querySelector('#offline').hidden && document.querySelector('#offline').textContent.includes('revoked')", "revoked session")
                assert cdp.evaluate("sessionStorage.getItem('companion:tracked-jobs:v2')===null"), \
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
            if generated_video:
                generated_video.unlink(missing_ok=True)
    print("companion browser: pairing, URL, upload progress, status, review, evidence, person, "
          "speaker confirm/undo, refresh recovery, revoke, bilingual and 390px passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
