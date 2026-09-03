#!/usr/bin/env python3
"""Exercise Experimental Live Context UI contracts through Chromium CDP.

Network-facing Live APIs are deterministic browser stubs. The page itself is served by the
isolated smoke server, and no source URL is fetched or meeting data mutated.
"""

from __future__ import annotations

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


def wait_for(cdp: CDP, expression: str, label: str, timeout: float = 12) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if cdp.evaluate(expression):
                return
        except RuntimeError as exc:
            if "Execution context was destroyed" not in str(exc):
                raise
        time.sleep(0.08)
    raise RuntimeError(f"Live Context browser timeout: {label}")


def main() -> int:
    if not CHROME:
        print("live context browser: chromium not found, skipped")
        return 0
    base = os.environ.get("MM_TEST_BASE", "http://127.0.0.1:8899")
    with tempfile.TemporaryDirectory(
        prefix="mm-chromium-live-context-", ignore_cleanup_errors=True,
    ) as tmp:
        profile = Path(tmp)
        process = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--remote-debugging-port=0", "--remote-allow-origins=*",
            f"--user-data-dir={profile}", "--window-size=1440,900", "about:blank",
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
window.__liveE2E = {errors: [], playCalls: 0, stopCalls: 0, polls: 0, session: null};
addEventListener('error', event => window.__liveE2E.errors.push(String(event.message)));
addEventListener('unhandledrejection', event =>
  window.__liveE2E.errors.push(String(event.reason?.message || event.reason)));
const originalPlay = HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play = function(...args) {
  window.__liveE2E.playCalls += 1;
  return Promise.resolve();
};
const originalFetch = window.fetch.bind(window);
const jsonResponse = (value, status = 200) => new Response(JSON.stringify(value), {
  status, headers: {'Content-Type': 'application/json'}
});
window.fetch = async (input, init = {}) => {
  const url = String(input);
  const method = String(init.method || 'GET').toUpperCase();
  if (url === '/api/live/probe' && method === 'POST') return jsonResponse({
    source: {kind: 'hls'},
    capture_plan: {mode: 'analyze_background', background_available: true}
  });
  if (url === '/api/live/sessions' && method === 'POST') {
    window.__liveE2E.session = {
      id: 'live-synthetic-browser', state: 'LIVE', duration: 38,
      text_signals: 2, source_kind: 'hls'
    };
    return jsonResponse(window.__liveE2E.session);
  }
  if (url === '/api/live/sessions' && method === 'GET')
    return jsonResponse({sessions: window.__liveE2E.session ? [window.__liveE2E.session] : []});
  if (url === '/api/live/sessions/live-synthetic-browser/stop' && method === 'POST') {
    window.__liveE2E.stopCalls += 1;
    window.__liveE2E.session = {...window.__liveE2E.session, state: 'FINALIZING'};
    return jsonResponse(window.__liveE2E.session);
  }
  if (url === '/api/live/sessions/live-synthetic-browser' && method === 'GET') {
    window.__liveE2E.polls += 1;
    if (window.__liveE2E.session?.state === 'FINALIZING')
      window.__liveE2E.session = {...window.__liveE2E.session, state: 'COMPLETE'};
    return jsonResponse(window.__liveE2E.session);
  }
  return originalFetch(input, init);
};
"""})
                cdp.call("Page.navigate", {"url": base})
                wait_for(cdp, "document.readyState === 'complete' && "
                         "!document.querySelector('#live-context-entry').classList.contains('hidden')",
                         "feature-flagged entry")

                baseline = cdp.evaluate(r"""
(() => {
  const entry = document.querySelector('#live-context-entry');
  entry.click();
  return {
    event: document.querySelector('[name="live-content-type"]:checked').value,
    mode: document.querySelector('[name="live-mode"]:checked').value,
    label: document.querySelector('[name="live-mode"]:checked').parentElement.textContent,
    dialog: document.querySelector('#live-context-form').getAttribute('role'),
  };
})()
""")
                assert baseline["event"] == "live_event"
                assert baseline["mode"] == "analyze_background"
                assert "无需播放" in baseline["label"]
                assert baseline["dialog"] == "dialog"

                choices = cdp.evaluate(r"""
(() => {
  document.querySelector('[name="live-mode"][value="watch_analyze"]').click();
  const watch = document.querySelector('[name="live-mode"]:checked').value;
  document.querySelector('[name="live-content-type"][value="meeting"]').click();
  const meeting = document.querySelector('[name="live-mode"]:checked').value;
  document.querySelector('[data-ui-language="en"]').click();
  return {watch, meeting, title: document.querySelector('#live-context-title').textContent,
    detail: document.querySelector('[name="live-mode"]:checked').parentElement.textContent};
})()
""")
                assert choices["watch"] == "watch_analyze"
                assert choices["meeting"] == "meeting_companion"
                assert choices["title"] == "Start Live Context"
                assert "listens quietly" in choices["detail"]

                started = cdp.evaluate(r"""
(async () => {
  document.querySelector('[name="live-content-type"][value="live_event"]').click();
  const input = document.querySelector('#live-source-input');
  input.value = 'https://example.invalid/live/master.m3u8';
  input.dispatchEvent(new Event('input', {bubbles: true}));
  document.querySelector('#live-context-form').requestSubmit();
  const end = Date.now() + 5000;
  while (Date.now() < end && document.querySelector('#live-active-status').classList.contains('hidden'))
    await new Promise(resolve => setTimeout(resolve, 25));
  return {state: document.querySelector('#live-active-state').textContent,
    playCalls: window.__liveE2E.playCalls, errors: window.__liveE2E.errors};
})()
""")
                assert started["state"].startswith("LIVE")
                assert started["playCalls"] == 0
                assert not started["errors"], started["errors"]

                closed = cdp.evaluate(r"""
(() => {
  document.querySelector('#live-context-close').click();
  return {hidden: document.querySelector('#live-context-mask').classList.contains('hidden'),
    stopCalls: window.__liveE2E.stopCalls};
})()
""")
                assert closed == {"hidden": True, "stopCalls": 0}

                cdp.evaluate("document.querySelector('#live-context-entry').focus()")
                cdp.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter"})
                cdp.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter"})
                wait_for(cdp, "!document.querySelector('#live-context-mask').classList.contains('hidden')",
                         "keyboard reopen")
                resumed = cdp.evaluate(r"""
({visible: !document.querySelector('#live-active-status').classList.contains('hidden'),
  state: document.querySelector('#live-active-state').textContent,
  stopCalls: window.__liveE2E.stopCalls})
""")
                assert resumed["visible"] and resumed["state"].startswith("LIVE")
                assert resumed["stopCalls"] == 0

                cdp.call("Emulation.setEmulatedMedia", {"features": [{
                    "name": "prefers-reduced-motion", "value": "reduce",
                }]})
                cdp.call("Emulation.setDeviceMetricsOverride", {
                    "width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True,
                })
                responsive = cdp.evaluate(r"""
({client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth,
  dialog: document.querySelector('#live-context-form').getBoundingClientRect().width,
  animations: document.querySelector('#live-context-form').getAnimations().length})
""")
                assert responsive["scroll"] <= responsive["client"], responsive
                assert responsive["dialog"] <= responsive["client"], responsive
                assert responsive["animations"] == 0, responsive

                cdp.evaluate("document.querySelector('#live-stop').click(); "
                             "document.querySelector('#live-stop-finalize').click()")
                wait_for(cdp, "document.querySelector('#live-active-state').textContent.includes('Finalizing')",
                         "finalizing state")
                wait_for(cdp, "document.querySelector('#live-active-state').textContent.startsWith('Complete')",
                         "complete state", timeout=8)
                result = cdp.evaluate(r"""
({stopCalls: window.__liveE2E.stopCalls, playCalls: window.__liveE2E.playCalls,
  errors: window.__liveE2E.errors, state: document.querySelector('#live-active-state').textContent})
""")
                assert result["stopCalls"] == 1
                assert result["playCalls"] == 0
                assert result["state"].startswith("Complete")
                assert not result["errors"], result["errors"]
            finally:
                cdp.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    print("live context browser: defaults, silence, resume, finalization, bilingual, keyboard and responsive contracts passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
