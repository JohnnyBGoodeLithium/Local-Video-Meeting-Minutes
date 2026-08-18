#!/usr/bin/env python3
"""可重排的单 worker 作业调度器。

本项目的重模型任务必须串行，但 FIFO 会让翻译挡住新会议。调度器只在任务尚未
开始时调整顺序；运行中的任务永不被抢占。
"""

from __future__ import annotations

import threading
from collections.abc import Callable


KIND_PRIORITIES = {
    "upload": 10,
    "retranscribe": 10,
    "regen": 20,
    "topic_map": 20,
    "orgchart_extract": 20,
    "translation": 30,
}
USER_PRIORITY = 0


def default_priority(kind: str) -> int:
    return KIND_PRIORITIES.get(str(kind or ""), 20)


class SerialPriorityExecutor:
    """单线程执行任务，并允许尚未开始的任务改变优先级。"""

    def __init__(self):
        self._condition = threading.Condition()
        self._pending: dict[str, dict] = {}
        self._sequence = 0
        self._closing = False
        self._error_handler: Callable[[dict, Exception], None] | None = None
        self._worker = threading.Thread(
            target=self._run, name="meeting-job-scheduler", daemon=True)
        self._worker.start()

    def set_error_handler(self, handler: Callable[[dict, Exception], None]) -> None:
        self._error_handler = handler

    def submit(self, function: Callable, job: dict, *args, **kwargs) -> None:
        jid = str(job["id"])
        with self._condition:
            if self._closing:
                raise RuntimeError("作业调度器已经关闭")
            if jid in self._pending:
                raise ValueError(f"作业已经排队: {jid}")
            self._sequence += 1
            priority = int(job.get("queue_priority", default_priority(job.get("kind", ""))))
            job["queue_priority"] = priority
            self._pending[jid] = {
                "function": function, "job": job, "args": args, "kwargs": kwargs,
                "priority": priority, "sequence": self._sequence,
            }
            self._condition.notify()

    def prioritize(self, jid: str) -> bool:
        """把一个仍在等待的任务提升为用户优先；不抢占运行中任务。"""
        with self._condition:
            item = self._pending.get(str(jid))
            if item is None:
                return False
            self._sequence += 1
            item["priority"] = USER_PRIORITY
            # 后一次手动置顶排在先前置顶任务之前，符合用户对“插队”的理解。
            item["sequence"] = -self._sequence
            item["job"]["queue_priority"] = USER_PRIORITY
            item["job"]["priority_boost"] = True
            self._condition.notify()
            return True

    def discard(self, jid: str) -> bool:
        """从等待队列移除已取消任务。"""
        with self._condition:
            removed = self._pending.pop(str(jid), None) is not None
            if removed:
                self._condition.notify()
            return removed

    def snapshot(self) -> list[dict]:
        with self._condition:
            ordered = sorted(
                self._pending.values(), key=lambda item: (item["priority"], item["sequence"]))
            return [
                {"id": item["job"]["id"], "position": index,
                 "priority": item["priority"],
                 "priority_boost": bool(item["job"].get("priority_boost"))}
                for index, item in enumerate(ordered, 1)
            ]

    def shutdown(self, wait: bool = True) -> None:
        with self._condition:
            self._closing = True
            self._condition.notify_all()
        if wait:
            self._worker.join()

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._closing:
                    self._condition.wait()
                if self._closing and not self._pending:
                    return
                jid, item = min(
                    self._pending.items(),
                    key=lambda pair: (pair[1]["priority"], pair[1]["sequence"]))
                self._pending.pop(jid)
            try:
                item["function"](item["job"], *item["args"], **item["kwargs"])
            except Exception as exc:  # pragma: no cover - 防止异常杀死唯一 worker
                if self._error_handler:
                    self._error_handler(item["job"], exc)
