#!/usr/bin/env python3
"""子进程异常日志只保留异常类型，不保存潜在私有错误消息。"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
sys.path.insert(0, str(PROJECT / "web"))

import job_store  # noqa: E402


assert job_store._safe_child_exception(
    "ValueError: private transcript fragment") == "[error] 子进程异常 (ValueError)"
assert job_store._safe_child_exception(
    "urllib.error.URLError: /private/local/path") == "[error] 子进程异常 (URLError)"
assert job_store._safe_child_exception("Traceback (most recent call last):") is None
assert job_store._safe_child_exception("ordinary model output") is None
job_store.EXEC.shutdown()

print("Job log safety: exception class retained, private message discarded")
