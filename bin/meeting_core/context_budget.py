"""本地模型上下文预算和稳定的按行切分策略。"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Iterable


DEFAULT_CONTEXT_WINDOW = int(os.environ.get("MEETING_LLM_CONTEXT_SIZE", "65536"))


def _is_dense_character(char: str) -> bool:
    code = ord(char)
    return (
        0x2E80 <= code <= 0x9FFF
        or 0xAC00 <= code <= 0xD7AF
        or 0x3040 <= code <= 0x30FF
        or 0xFF00 <= code <= 0xFFEF
    )


def estimate_text_tokens(text: str) -> int:
    """保守估算中英混合文本 token 数，不依赖正在运行的模型服务。

    中日韩字符按一字符一 token，其余文本按约三字符一 token，再保留少量协议
    开销。该估算有意偏大，避免草稿这种后台任务再次撞到服务端 context limit。
    """
    value = str(text or "")
    dense = sum(1 for char in value if _is_dense_character(char))
    other = len(value) - dense
    return dense + math.ceil(other / 3) + 128


@dataclass(frozen=True)
class ContextBudget:
    context_window: int = DEFAULT_CONTEXT_WINDOW
    output_tokens: int = 8192
    safety_tokens: int = 4096

    @property
    def input_tokens(self) -> int:
        return max(1024, self.context_window - self.output_tokens - self.safety_tokens)

    def fits(self, text: str) -> bool:
        return estimate_text_tokens(text) <= self.input_tokens


def split_json_rows(rows: Iterable[dict], target_tokens: int) -> list[list[dict]]:
    """按估算 token 预算切连续 JSON 行，保持原顺序和稳定 ID。"""
    limit = max(1024, int(target_tokens))
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_tokens = 0
    for row in rows:
        encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        row_tokens = estimate_text_tokens(encoded)
        if current and current_tokens + row_tokens > limit:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(row)
        current_tokens += row_tokens
    if current:
        chunks.append(current)
    return chunks
