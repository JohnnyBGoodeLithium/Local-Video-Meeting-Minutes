"""本机 OpenAI-compatible 文本模型客户端。

模型地址、thinking 开关、超时和错误分类只在这里维护。模块拒绝非 loopback
地址，除非管理员显式设置 ``MEETING_ALLOW_REMOTE_LLM=1``。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse


DEFAULT_API = os.environ.get("MEETING_LLM_API", "http://127.0.0.1:11435/v1").rstrip("/")
DEFAULT_MODEL = os.environ.get("MEETING_LLM_MODEL", "qwen3.6-35b-a3b-operator")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class LLMError(RuntimeError):
    """可安全展示、不包含请求正文的模型错误。"""


class LLMContextError(LLMError):
    pass


class LLMResponseError(LLMError):
    pass


@dataclass(frozen=True)
class Completion:
    content: str
    usage: dict
    elapsed: float


class LocalLLMClient:
    def __init__(self, *, api: str = DEFAULT_API, model: str = DEFAULT_MODEL,
                 timeout: int = 1800):
        parsed = urlparse(api)
        allow_remote = os.environ.get("MEETING_ALLOW_REMOTE_LLM") == "1"
        if parsed.hostname not in LOOPBACK_HOSTS and not allow_remote:
            raise ValueError("文本模型地址必须是本机回环地址")
        self.api = api.rstrip("/")
        self.model = model
        self.timeout = int(timeout)

    def complete(self, prompt: str, *, system: str | None = None,
                 max_tokens: int = 4096, temperature: float = 0.2) -> Completion:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
            "chat_template_kwargs": {"enable_thinking": False},
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api}/chat/completions", data=body,
            headers={"Content-Type": "application/json"})
        started = time.time()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 400:
                raise LLMContextError("本地文本模型拒绝了请求（HTTP 400，通常是上下文超限）") from exc
            raise LLMError(f"本地文本模型请求失败（HTTP {exc.code}）") from exc
        except Exception as exc:
            raise LLMError(f"无法连接本地文本模型（{type(exc).__name__}）") from exc
        try:
            content = str(data["choices"][0]["message"].get("content") or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("本地文本模型返回格式不可读") from exc
        if not content:
            raise LLMResponseError("本地文本模型没有返回可读正文")
        return Completion(content=content, usage=data.get("usage") or {},
                          elapsed=time.time() - started)
