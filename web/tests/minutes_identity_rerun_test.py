#!/usr/bin/env python3
"""中途改说话人的重跑防护：逐字稿连续变化时等待稳定后再重跑，且有总等待上限。"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))

from minutes_by_page import _wait_transcript_stable  # noqa: E402

# 文件稳定：等待一个静默窗口后立即返回，不拖到上限
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "transcript.spk.json"
    p.write_text("[]", encoding="utf-8")
    t0 = time.time()
    _wait_transcript_stable(p, quiet_seconds=2, max_wait_seconds=30, poll_seconds=1)
    elapsed = time.time() - t0
    assert 2 <= elapsed < 10, f"稳定文件应约 2s 返回，实际 {elapsed:.1f}s"

# 文件连续变化：会一直等到稳定；总耗时明显超过首次变化时刻
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "transcript.spk.json"
    p.write_text("[]", encoding="utf-8")
    stop = False

    def writer():
        n = 0
        while not stop and n < 4:  # 模拟连续绑定 4 个说话人
            time.sleep(1.2)
            p.write_text(f"[{n}]", encoding="utf-8")
            n += 1

    thread = threading.Thread(target=writer)
    thread.start()
    t0 = time.time()
    _wait_transcript_stable(p, quiet_seconds=2, max_wait_seconds=30, poll_seconds=1)
    elapsed = time.time() - t0
    stop = True
    thread.join()
    assert elapsed >= 4.5, f"连续变化时应等到最后一次写入稳定，实际 {elapsed:.1f}s"

# 一直变个不停：到上限也返回，不阻塞管线
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "transcript.spk.json"
    p.write_text("[]", encoding="utf-8")
    stop = False

    def churn():
        n = 0
        while not stop:
            p.write_text(f"[{n}]", encoding="utf-8")
            n += 1
            time.sleep(0.4)

    thread = threading.Thread(target=churn)
    thread.start()
    t0 = time.time()
    _wait_transcript_stable(p, quiet_seconds=60, max_wait_seconds=3, poll_seconds=1)
    elapsed = time.time() - t0
    stop = True
    thread.join()
    assert 3 <= elapsed < 12, f"超过上限必须返回，实际 {elapsed:.1f}s"

print("Identity rerun: transcript stability wait and cap passed")
