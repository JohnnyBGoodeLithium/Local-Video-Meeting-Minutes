#!/usr/bin/env python3
"""单 worker 队列按类型排序，并支持等待任务手动插队。"""

from __future__ import annotations

import sys
import threading
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
from job_scheduler import SerialPriorityExecutor  # noqa: E402


executor = SerialPriorityExecutor()
started = threading.Event()
release = threading.Event()
done = threading.Event()
order = []


def blocker(job):
    started.set()
    release.wait(3)
    order.append(job["id"])


def record(job):
    order.append(job["id"])
    if len(order) == 3:
        done.set()


executor.submit(blocker, {"id": "running", "kind": "upload"})
assert started.wait(1)
translation = {"id": "translation", "kind": "translation"}
upload = {"id": "upload", "kind": "upload"}
executor.submit(record, translation)
executor.submit(record, upload)
assert [item["id"] for item in executor.snapshot()] == ["upload", "translation"]
assert executor.prioritize("translation") is True
snapshot = executor.snapshot()
assert [item["id"] for item in snapshot] == ["translation", "upload"]
assert snapshot[0]["position"] == 1 and snapshot[0]["priority_boost"] is True
release.set()
assert done.wait(2)
executor.shutdown()
assert order == ["running", "translation", "upload"]

print("Job scheduler: type priority, manual boost, and serial execution passed")
