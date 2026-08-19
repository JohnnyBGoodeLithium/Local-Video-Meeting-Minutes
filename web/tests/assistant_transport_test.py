#!/usr/bin/env python3
"""本地助手传输层：输出被模型截断时必须显式失败，不能伪装完成。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
sys.path.insert(0, str(PROJECT / "web"))

import assistant_service as assistant  # noqa: E402


class FakeResponse:
    def __init__(self, payload=None, lines=None):
        self.payload = payload
        self.lines = lines or []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode()

    def __iter__(self):
        return iter(self.lines)


original = assistant.urllib.request.urlopen
try:
    assistant.urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(payload={
        "choices": [{"finish_reason": "length", "message": {"content": "未完整"}}]
    })
    try:
        assistant._chat([{"role": "user", "content": "虚构长问题"}])
        raise AssertionError("non-stream length finish must be rejected")
    except assistant.AssistantUnavailable as exc:
        assert "长度上限" in str(exc)

    frames = [
        b'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\n\n',
        b'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n',
        b'data: [DONE]\n\n',
    ]
    assistant.urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(lines=frames)
    generated = assistant._chat_stream([{"role": "user", "content": "虚构长问题"}])
    assert next(generated) == "partial"
    try:
        next(generated)
        raise AssertionError("stream length finish must be rejected")
    except assistant.AssistantUnavailable as exc:
        assert "未完成内容" in str(exc)
finally:
    assistant.urllib.request.urlopen = original

print("Assistant transport: truncated outputs are explicit failures")
