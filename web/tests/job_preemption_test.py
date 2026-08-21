#!/usr/bin/env python3
"""强制调度只暂停有检查点的运行项，并排入急件后的自动续跑。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT / "web"), str(PROJECT / "bin")]


with tempfile.TemporaryDirectory(prefix="meeting-preemption-") as tmp:
    root = Path(tmp)
    os.environ["MEETING_DATA_ROOT"] = str(root)
    os.environ["MEETING_WEB_JOBS"] = str(root / "jobs")
    (root / "jobs").mkdir()

    import job_store  # noqa: E402
    import routers.jobs as job_routes  # noqa: E402

    meeting = root / "meetings" / "synthetic-running"
    meeting.mkdir(parents=True)
    (meeting / "transcript.spk.json").write_text("[]", encoding="utf-8")
    (meeting / "slides.json").write_text("[]", encoding="utf-8")
    (meeting / "source_video.mp4").write_bytes(b"fictional protected video")

    running = {
        "id": "running001", "kind": "upload", "status": "running",
        "created": 1.0, "started": 2.0, "finished": None, "rc": None,
        "meeting": "synthetic-running", "stage": "理解共享画面", "log": [],
        "cmd": ["python", "synthetic.py"], "inbox": "recordings/inbox/running001",
    }
    target = {
        "id": "urgent001", "kind": "upload", "status": "queued",
        "created": 3.0, "started": None, "finished": None, "rc": None,
        "meeting": "synthetic-urgent", "stage": "等待处理", "log": [],
        "cmd": ["python", "synthetic.py"], "queue_priority": 10,
    }
    job_store.JOBS.clear()
    job_store.JOBS.update({running["id"]: running, target["id"]: target})

    class FakeProc:
        def poll(self):
            return None

    class FakeExecutor:
        def __init__(self):
            self.submitted = []

        def prioritize(self, jid):
            return jid == target["id"]

        def submit(self, _function, job):
            self.submitted.append(job)

        def snapshot(self):
            ids = [target["id"], *(job["id"] for job in self.submitted)]
            return [{"id": jid, "position": index, "priority": 0,
                     "priority_boost": True}
                    for index, jid in enumerate(ids, 1)]

    fake_executor = FakeExecutor()
    stopped = []
    job_routes.EXEC = fake_executor
    job_routes.PROCS.clear()
    job_routes.PROCS[running["id"]] = FakeProc()
    job_routes._terminate_process_group = stopped.append

    result = job_routes.force_prioritize_job(target["id"])
    successor = fake_executor.submitted[0]
    assert result["ok"] is True and result["queue_position"] == 1
    assert running["status"] == "paused" and running["pause_requested"] is True
    assert running["preempted_by"] == target["id"] and stopped == [running["id"]]
    assert target["priority_boost"] is True and target["forced_after"] == running["id"]
    assert successor["kind"] == "regen" and successor["auto_resume"] is True
    assert successor["resume_after"] == target["id"] and successor["retry_of"] == running["id"]
    assert successor["queue_priority"] == 0 and successor["inbox"] == running["inbox"]
    assert running["recovered_by"] == successor["id"]

print("Job preemption: safe pause, urgent order, and automatic resume passed")
