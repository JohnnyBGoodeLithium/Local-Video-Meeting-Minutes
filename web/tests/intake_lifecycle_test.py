#!/usr/bin/env python3
"""合成导入生命周期：重复拖拽、删除、分类及取消/启动竞争；不调用模型。"""
import asyncio
import io
import json
import os
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "web"), str(ROOT / "bin")]


class Queue:
    def __init__(self):
        self.items = []

    def submit(self, _function, job):
        self.items.append(job)

    def discard(self, jid):
        self.items = [job for job in self.items if job["id"] != jid]


class Response:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def json(self):
        return self.body


def reply(function, *args, **kwargs):
    """直接覆盖路由/队列竞争；真实 HTTP multipart 另由完整 smoke 验证。"""
    try:
        return Response(200, function(*args, **kwargs))
    except HTTPException as exc:
        return Response(exc.status_code, {"detail": exc.detail})


with tempfile.TemporaryDirectory(prefix="intake-lifecycle-") as tmp:
    root = Path(tmp)
    os.environ.update(MEETING_DATA_ROOT=tmp, MEETING_WEB_JOBS=str(root / "jobs"))
    (root / "jobs").mkdir()
    import deps
    import job_store as store
    from routers import jobs, meetings

    store.EXEC.shutdown()
    jobs.EXEC = Queue()
    def upload(mode="meeting", name="20260102_Fictional_Training.mp4", visual_mode=""):
        file = UploadFile(filename=name, file=io.BytesIO(b"synthetic video"))
        return reply(asyncio.run, jobs.upload_with_limit(
            [file], content_type=mode, visual_mode=visual_mode))

    old = upload("media").json()
    assert old["status"] == "queued" and "--media" in old["cmd"]
    assert "fresh_import" not in old
    slug = old["meeting"]
    mdir = deps.MEETINGS / slug
    # 初次任务还没有创建目录时，重复导入也必须被原子拒绝。
    conflict = upload()
    assert conflict.status_code == 409 and "任务队列" in conflict.json()["detail"]
    assert len(store.JOBS) == len(jobs.EXEC.items) == 1
    inbox = root / old["inbox"]
    assert list(deps.INBOX.iterdir()) == [inbox] and inbox.is_dir()

    mdir.mkdir(parents=True)
    (mdir / "meta.json").write_text('{"title":"Fictional","content_type":"media"}')
    (mdir / "transcript.spk.json").write_text('[{"text":"Synthetic protected text"}]')
    (mdir / "minutes.md").write_text("# Synthetic protected minutes")
    before = {p.name: p.read_bytes() for p in mdir.iterdir()}
    deps.EVALUATIONS_DIR.mkdir()
    evaluation = deps.EVALUATIONS_DIR / f"{slug}.json"
    evaluation.write_text("{}")

    for state in ("queued", "running"):
        store.JOBS[old["id"]]["status"] = state
        with patch.object(meetings.vb, "load_bank") as bank:
            blocked = reply(meetings.delete_meeting, slug)
            assert blocked.status_code == 409 and "取消" in blocked.json()["detail"]
            bank.assert_not_called()
        assert reply(meetings.set_content_type, slug, content_type="meeting").status_code == 409
        assert evaluation.is_file()
        assert all((mdir / name).read_bytes() == value for name, value in before.items())

    # 取消状态已落盘但进程尚未退出时仍不能删除。
    store.JOBS[old["id"]]["status"] = "cancelled"
    class Alive:
        def poll(self):
            return None
    store.PROCS[old["id"]] = Alive()
    assert reply(meetings.delete_meeting, slug).status_code == 409
    store.PROCS.clear()

    # 已停止记录通过“重新分类”保留原结果，重复上传仍不覆盖。
    classified = reply(meetings.set_content_type, slug, content_type="meeting")
    assert classified.status_code == 200 and classified.json()["content_type"] == "meeting"
    assert upload().status_code == 409
    assert (mdir / "transcript.spk.json").read_bytes() == before["transcript.spk.json"]
    assert (mdir / "minutes.md").read_bytes() == before["minutes.md"]
    assert list(deps.INBOX.iterdir()) == [inbox]

    # 用户明确删除后才可导入；迟到的派生任务不能重新创建已删除资料。
    assert reply(meetings.delete_meeting, slug).status_code == 200
    assert not mdir.exists() and not evaluation.exists() and inbox.exists()
    try:
        store._new_job("translation", meeting=slug)
        raise AssertionError("deleted source accepted")
    except HTTPException as exc:
        assert exc.status_code == 409
    reimport = upload().json()
    assert reimport["status"] == "queued" and reimport["content_type"] == "meeting"
    assert "--media" not in reimport["cmd"]

    # 两次同时上传，在入队前汇合；不同内容分类也不能生成两份任务。
    barrier = threading.Barrier(2)
    new_job = store._new_job
    def synchronized_new(*args, **kwargs):
        barrier.wait(timeout=5)
        return new_job(*args, **kwargs)
    with patch.object(jobs, "_new_job", side_effect=synchronized_new), ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(upload, mode, "20260103_Concurrent.mp4")
                   for mode in ("meeting", "media")]
        responses = [future.result(timeout=10) for future in futures]
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert len(list(deps.INBOX.iterdir())) == 3  # 原任务、新导入、并发胜者

    # 媒体语义与屏幕抽帧独立；不会为了过滤参会人强制变成会议纪要。
    screen = upload("media", "20260104_Screen_Training.mp4", "slides").json()
    assert screen["content_type"] == "media" and screen["visual_mode"] == "slides"
    assert "--media" in screen["cmd"]
    assert screen["cmd"][-2:] == ["--visual-mode", "slides"]
    assert upload("media", "invalid.mp4", "unknown").status_code == 400
    url_job = reply(jobs.import_media_url, jobs.MediaURLImport(
        url="https://example.invalid/video", visual_mode="slides")).json()
    assert url_job["content_type"] == "media" and url_job["cmd"][-2:] == ["--visual-mode", "slides"]

    # 启动尚未返回 Popen 时发生取消：登记与取消使用同一把锁，进程必被停止。
    entered, release, stopped, cancelling = (threading.Event() for _ in range(4))
    class FakeProcess:
        returncode = None
        def __init__(self, *args, **kwargs):
            entered.set()
            assert release.wait(5)
            self.stdout = self.lines()
        def lines(self):
            assert stopped.wait(5)
            yield "[meta] synthetic process stopped"
        def wait(self, *args, **kwargs):
            self.returncode = -15
            return self.returncode
        def poll(self):
            return self.returncode
    def terminate(jid):
        assert jid in store.PROCS  # 取消不会错过登记中的进程
        stopped.set()
    def cancel(jid):
        cancelling.set()
        return jobs.cancel_job(jid)
    running = store.JOBS[reimport["id"]]
    with patch.object(store.subprocess, "Popen", FakeProcess), \
            patch.object(jobs, "_terminate_process_group", side_effect=terminate), \
            ThreadPoolExecutor(2) as pool:
        worker = pool.submit(store._run_pipeline, running)
        assert entered.wait(5)
        cancellation = pool.submit(cancel, running["id"])
        assert cancelling.wait(5) and not cancellation.done()
        release.set()
        assert cancellation.result(timeout=10)["ok"]
        worker.result(timeout=10)
    assert running["status"] == "cancelled" and not store.PROCS
    assert json.loads((root / "jobs" / f"{running['id']}.json").read_text())["status"] == "cancelled"

print("Intake lifecycle: deletion protection, classification, duplicate/concurrent uploads and cancellation passed")
