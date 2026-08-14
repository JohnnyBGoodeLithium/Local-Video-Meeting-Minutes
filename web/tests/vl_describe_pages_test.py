"""describe_pages 并发与缓存落盘测试：本地 stub VL 服务，不依赖 GPU/真实模型。
验证：缺页并发请求（耗时显著低于串行下限）、每页完成即原子写缓存、
空正文页（详细+紧凑都为空）不进成功缓存。"""
import base64
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "bin"))
os.environ["MEETING_VL_WORKERS"] = "2"

import minutes_by_page  # noqa: E402

DELAY = 0.35
EMPTY_MARKER = base64.b64encode(b"empty-page").decode()

STUB_OK = {"choices": [{"message": {"content": "## 标题\n测试页\n## 页面内容\n- 要点"}}],
           "usage": {"completion_tokens": 10}}
STUB_EMPTY = {"choices": [{"message": {"content": ""}}], "usage": {"completion_tokens": 0}}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/models":
            self._json({"data": [{"id": "stub-vl"}]})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = self.rfile.read(length)
        time.sleep(DELAY)  # 模拟推理耗时；串行会线性累加，双槽并发应显著重叠
        self._json(STUB_EMPTY if EMPTY_MARKER.encode() in payload else STUB_OK)


with tempfile.TemporaryDirectory() as td:
    mdir = Path(td)
    (mdir / "slides").mkdir()
    pages = []
    for n in range(1, 6):
        marker = b"empty-page" if n == 3 else f"page-{n}".encode()
        (mdir / "slides" / f"p{n}.jpg").write_bytes(marker)
        pages.append({"page": n, "image": f"p{n}.jpg", "first": n * 10.0})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    api = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        t0 = time.time()
        descs = minutes_by_page.describe_pages(mdir, pages, api)
        elapsed = time.time() - t0
        # 6 次调用(第 3 页详细+紧凑各一次)串行下限 6×DELAY=2.1s；双槽应明显更低
        assert set(descs) == {1, 2, 4, 5}, descs.keys()
        assert elapsed < 1.9, f"疑似未并发: {elapsed:.2f}s"
        cache = json.loads((mdir / "page_desc.json").read_text(encoding="utf-8"))
        assert set(cache["desc"]) == {"1", "2", "4", "5"}, cache["desc"].keys()
        # 重跑只补第 3 页(2 次调用 ≈0.7s)，其余命中缓存
        t0 = time.time()
        descs2 = minutes_by_page.describe_pages(mdir, pages, api)
        elapsed2 = time.time() - t0
        assert set(descs2) == {1, 2, 4, 5}, descs2.keys()
        assert elapsed2 < 1.4, f"缓存未生效: {elapsed2:.2f}s"
    finally:
        server.shutdown()

print("VL describe_pages: concurrency and cache passed")
