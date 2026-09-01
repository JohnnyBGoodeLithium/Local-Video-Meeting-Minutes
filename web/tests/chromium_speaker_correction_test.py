#!/usr/bin/env python3
"""Drive the isolated workspace through the speaker-correction journey via CDP.

The test uses only the synthetic smoke meeting. Write responses are deterministic browser
stubs so the shared smoke fixture stays immutable; server contracts are covered separately
by API/unit tests.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


CHROME = (shutil.which("chromium") or shutil.which("chromium-browser")
          or shutil.which("google-chrome"))


class CDP:
    def __init__(self, url: str):
        parsed = urlparse(url)
        self.sock = socket.create_connection((parsed.hostname, parsed.port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (f"GET {parsed.path} HTTP/1.1\r\nHost: {parsed.netloc}\r\n"
                   "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(request.encode())
        response = self.sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"CDP websocket handshake failed: {response[:120]!r}")
        self.next_id = 0

    def _send_text(self, text: str) -> None:
        payload = text.encode()
        mask = os.urandom(4)
        size = len(payload)
        header = bytearray([0x81])
        if size < 126:
            header.append(0x80 | size)
        elif size < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", size))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", size))
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def _recv_text(self) -> str:
        first = self.sock.recv(2)
        if len(first) != 2:
            raise RuntimeError("CDP websocket closed")
        opcode = first[0] & 0x0F
        size = first[1] & 0x7F
        if size == 126:
            size = struct.unpack("!H", self._read(2))[0]
        elif size == 127:
            size = struct.unpack("!Q", self._read(8))[0]
        masked = bool(first[1] & 0x80)
        mask = self._read(4) if masked else None
        payload = self._read(size)
        if mask:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        if opcode == 0x9:
            self.sock.sendall(b"\x8a\x00")
            return self._recv_text()
        if opcode != 0x1:
            return self._recv_text()
        return payload.decode()

    def _read(self, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self.sock.recv(size - len(chunks))
            if not chunk:
                raise RuntimeError("CDP websocket closed")
            chunks.extend(chunk)
        return bytes(chunks)

    def call(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        request_id = self.next_id
        self._send_text(json.dumps({"id": request_id, "method": method,
                                    "params": params or {}}))
        while True:
            message = json.loads(self._recv_text())
            if message.get("id") == request_id:
                if message.get("error"):
                    raise RuntimeError(message["error"])
                return message.get("result", {})

    def evaluate(self, expression: str) -> object:
        result = self.call("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
        })
        value = result.get("result", {})
        if value.get("subtype") == "error":
            raise RuntimeError(value.get("description") or value)
        return value.get("value")

    def close(self) -> None:
        self.sock.close()


def wait_devtools_port(path: Path, timeout: float = 10) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if lines:
                return int(lines[0])
        except (FileNotFoundError, ValueError):
            pass
        time.sleep(0.05)
    raise RuntimeError("Chromium DevTools endpoint did not become readable")


def main() -> int:
    if not CHROME:
        print("speaker correction browser: chromium not found, skipped")
        return 0
    base = os.environ.get("MM_TEST_BASE", "http://127.0.0.1:8899")
    # Chromium children can finish touching the profile just after the parent exits.
    # The browser assertions must remain strict; only this runner-cleanup race is ignored.
    with tempfile.TemporaryDirectory(
        prefix="mm-chromium-correction-", ignore_cleanup_errors=True,
    ) as tmp:
        profile = Path(tmp)
        process = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--remote-debugging-port=0", "--remote-allow-origins=*",
            f"--user-data-dir={profile}", "--window-size=1600,900", base,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            active = profile / "DevToolsActivePort"
            port = wait_devtools_port(active)
            deadline = time.time() + 10
            target = None
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
                ready_deadline = time.time() + 12
                while time.time() < ready_deadline:
                    try:
                        if cdp.evaluate("document.readyState === 'complete' && !!document.querySelector('#turn-1 .chip')"):
                            break
                    except RuntimeError as exc:
                        if "Execution context was destroyed" not in str(exc):
                            raise
                    time.sleep(0.1)
                else:
                    raise RuntimeError("workspace did not finish loading")
                cdp.evaluate(r"""
window.__speakerCorrectionE2E = 'running';
void (async () => {
  const waitFor = async (fn, label, timeout = 9000) => {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      const value = fn();
      if (value) return value;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    throw new Error(`timeout: ${label}`);
  };
  await waitFor(() => document.querySelector('#turn-1 .chip'), 'transcript');
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input);
    // Language switching normally auto-starts three derived translations. This browser
    // journey verifies presentation only and must not mutate the isolated API fixture.
    if (url.includes('/translations/') && String(init?.method || 'GET').toUpperCase() === 'POST')
      return new Response(JSON.stringify({state: 'missing'}),
        {status: 200, headers: {'Content-Type': 'application/json'}});
    if (url.endsWith('/bind')) return new Response(JSON.stringify({
      ok: true, turns: 1, name: 'Alice Example'
    }), {status: 200, headers: {'Content-Type': 'application/json'}});
    if (url.endsWith('/speakers/undo')) return new Response(JSON.stringify({
      ok: true
    }), {status: 200, headers: {'Content-Type': 'application/json'}});
    if (url.endsWith('/split/preview')) return new Response(JSON.stringify({
      ok: true, voice: 'v_9001', selected: [0], suggested: [2], protected: [],
      ambiguous: [], direct_only: false,
      groups: [{group_key: 'group-1', selected: [0], suggested: [2], duration: 2.5,
        representative_turns: [0, 2], suggested_person: 'Alice Example'}]
    }), {status: 200, headers: {'Content-Type': 'application/json'}});
    if (url.endsWith('/split')) return new Response(JSON.stringify({
      ok: true, moved: 1, clusters: 1, turn_indexes: [0],
      voices: [{group_key: 'group-1', turn_indexes: [0], name: 'Alice Example'}]
    }), {status: 200, headers: {'Content-Type': 'application/json'}});
    return realFetch(input, init);
  };
  document.querySelector('[data-ui-language="en"]').click();
  await waitFor(() => document.documentElement.lang === 'en', 'English UI');
  const oneImportIcon = document.querySelectorAll('#pick-btn svg').length === 1
    && !/^[+＋]/.test(document.querySelector('#pick-btn span')?.textContent.trim() || '');

  // Lightweight identity confirmation followed by the nearby undo action.
  document.querySelector('#turn-1 .chip').click();
  const identity = await waitFor(() => document.querySelector(
    '#speaker-identity-popover:not(.hidden) [data-person-input]'), 'identity card');
  const englishIdentity = document.querySelector('#speaker-identity-popover h3')?.textContent.trim()
    === 'Who is this speaker?';
  identity.value = 'Alice Example';
  identity.dispatchEvent(new Event('input', { bubbles: true }));
  document.querySelector('#speaker-identity-popover [data-confirm]').click();
  const notice = await waitFor(() => document.querySelector(
    '#speaker-change-notice:not(.hidden) button'), 'identity success');
  notice.click();
  await waitFor(() => document.querySelector('#turn-1 .chip')?.textContent.trim() === 'Bob',
    'undo identity');

  // Exercise the complete advanced view with deterministic preview/apply contracts.
  document.querySelector('#turn-0 .chip').click();
  await waitFor(() => document.querySelector('#speaker-identity-popover:not(.hidden) [data-repair]'),
    'advanced entry');
  document.querySelector('#speaker-identity-popover [data-repair]').click();
  const englishRepair = await waitFor(() => document.querySelector(
    '#speaker-correction-sheet:not(.hidden) h3')?.textContent.trim() === 'Fix mixed speakers',
    'English mixed-speaker view');
  const example = await waitFor(() => document.querySelector(
    '#speaker-correction-sheet:not(.hidden) [data-example="0"]'), 'example selection');
  example.click();
  document.querySelector('#speaker-correction-sheet [data-primary]').click();
  await waitFor(() => document.querySelector(
    '#speaker-correction-sheet [data-group="group-1"]'), 'multi-group preview');
  const conservative = !document.querySelector('[data-include-suggested]').checked;
  document.querySelector('#speaker-correction-sheet [data-primary]').click();
  await waitFor(() => document.querySelector('#speaker-change-notice:not(.hidden)'),
    'advanced apply');
  document.querySelector('#export-btn').click();
  await waitFor(() => document.querySelectorAll(
    '#export-preflight input[name="export-profile"]').length === 2, 'two export choices');
  window.__speakerCorrectionE2E = [
    document.querySelector('#turn-1 .chip')?.textContent.trim() === 'Bob',
    conservative,
    document.querySelector('#speaker-correction-sheet').classList.contains('hidden'),
    document.querySelectorAll('#export-preflight input[name="export-profile"]').length === 2,
    englishIdentity,
    Boolean(englishRepair),
    oneImportIcon,
  ].join('|');
})().catch(error => {
  window.__speakerCorrectionE2E = `error:${error?.stack || error}`;
});
""")
                result = "running"
                result_deadline = time.time() + 20
                while time.time() < result_deadline:
                    result = cdp.evaluate("window.__speakerCorrectionE2E || ''")
                    if result != "running":
                        break
                    time.sleep(0.1)
            finally:
                cdp.close()
            if result != "true|true|true|true|true|true|true":
                raise RuntimeError(f"unexpected browser result: {result!r}")
            print("speaker correction browser: identity/undo and advanced preview/apply passed")
            return 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
