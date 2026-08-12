#!/usr/bin/env python3
"""语音草稿请求必须关闭 thinking，确保 completion 预算用于可读正文。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
import summarize  # noqa: E402
from meeting_core import llm  # noqa: E402


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({
            "choices": [{"message": {"content": "# 会议纪要\n\n- 合成测试结论"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8},
        }).encode("utf-8")


captured = {}


def fake_urlopen(request, timeout):
    captured.update(json.loads(request.data))
    assert timeout == 1800
    return FakeResponse()


with tempfile.TemporaryDirectory(prefix="summarize-request-test-") as temp:
    root = Path(temp)
    transcript = root / "transcript.txt"
    transcript.write_text("这是完全虚构的测试逐字稿。", encoding="utf-8")
    original_argv = sys.argv
    original_urlopen = llm.urllib.request.urlopen
    try:
        llm.urllib.request.urlopen = fake_urlopen
        sys.argv = ["summarize.py", str(transcript), "--out", str(root)]
        assert summarize.main() == 0
    finally:
        sys.argv = original_argv
        llm.urllib.request.urlopen = original_urlopen
    assert captured.get("chat_template_kwargs") == {"enable_thinking": False}
    assert (root / "minutes.md").is_file()

print("Summarize request: thinking disabled and readable content persisted")
