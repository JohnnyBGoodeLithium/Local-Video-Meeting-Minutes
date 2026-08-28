#!/usr/bin/env python3
"""冒烟测试专用的最小 WeKnora API；只计请求，不保存或打印正文。"""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    counter = 0

    def log_message(self, _format, *_args):
        return

    def _reply(self, status=200, data=None):
        payload = json.dumps({"success": status < 400, "data": data or {}}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _authorized(self):
        if self.headers.get("X-API-Key") == "smoke-key":
            return True
        self._reply(401)
        return False

    def do_GET(self):
        if self.path in {"/health", "/api/health"}:
            return self._reply(data={"ok": True})
        self._reply(404)

    def do_POST(self):
        if not self._authorized():
            return
        size = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(size) if size else b""
        if re.fullmatch(r"/api/v1/knowledge-bases/[^/]+/knowledge/(manual|file)", self.path):
            if self.path.endswith("/manual"):
                try:
                    if json.loads(body).get("status") != "publish":
                        return self._reply(400)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return self._reply(400)
            Handler.counter += 1
            return self._reply(201, {"id": f"smoke-doc-{Handler.counter}",
                                     "parse_status": "processing"})
        self._reply(404)

    def do_PUT(self):
        if not self._authorized():
            return
        size = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(size) if size else b""
        match = re.fullmatch(r"/api/v1/knowledge/manual/([^/]+)", self.path)
        if match:
            try:
                if json.loads(body).get("status") != "publish":
                    return self._reply(400)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._reply(400)
            return self._reply(data={"id": match.group(1), "parse_status": "processing"})
        self._reply(404)

    def do_DELETE(self):
        if not self._authorized():
            return
        if re.fullmatch(r"/api/v1/knowledge/[^/]+", self.path):
            return self._reply(data={"deleted": True})
        self._reply(404)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.environ["FAKE_WEKNORA_PORT"])), Handler).serve_forever()
