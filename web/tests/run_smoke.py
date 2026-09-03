#!/usr/bin/env python3
"""在一次性数据根中启动 Web 服务并运行冒烟测试。

真实 recordings/meetings/speaker_bank/web/jobs 均不会被读取或写入。
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
PY = PROJECT / ".venv" / "bin" / "python"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_ready(base: str, proc: subprocess.Popen, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"测试服务提前退出 (rc={proc.returncode})")
        try:
            with urllib.request.urlopen(f"{base}/api/health", timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.1)
    raise RuntimeError("测试服务启动超时")


def main() -> int:
    if not PY.is_file():
        print(f"[error] 找不到虚拟环境 Python: {PY}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="meeting-minutes-smoke-") as tmp:
        root = Path(tmp)
        data = root / "data"
        bank = root / "bank"
        jobs = root / "jobs"
        port = free_port()
        weknora_port = free_port()
        base = f"http://127.0.0.1:{port}"
        env = {
            **os.environ,
            "MM_TEST_ROOT": str(data),
            "MM_TEST_BANK": str(bank),
            "MM_TEST_JOBS": str(jobs),
            "MM_TEST_BASE": base,
            "MEETING_DATA_ROOT": str(data),
            "MEETING_WEB_BANK": str(bank),
            "MEETING_WEB_JOBS": str(jobs),
            "MEETING_WEB_PORT": str(port),
            "MEETING_WEB_DRYRUN": "1",
            "MEETING_WEB_DRYRUN_DELAY": "0.4",
            "MEETING_LIVE_CONTEXT": "1",
            "MEETING_RAG_MODE": "lexical",
            "PYTHONUNBUFFERED": "1",
            "MEETING_KB_PROVIDER": "weknora",
            "MEETING_KB_URL": f"http://127.0.0.1:{weknora_port}",
            "MEETING_KB_API_URL": f"http://127.0.0.1:{weknora_port}",
            "MEETING_KB_API_KEY": "smoke-key",
            "MEETING_KB_DEFAULT_ID": "kb-smoke-001",
            "MEETING_KB_DEFAULT_NAME": "Synthetic KB",
            "FAKE_WEKNORA_PORT": str(weknora_port),
        }
        subprocess.run([str(PY), str(PROJECT / "web/tests/make_fake_bank.py")],
                       env=env, cwd=PROJECT, check=True)
        subprocess.run([str(PY), str(PROJECT / "web/tests/make_smoke.py")],
                       env=env, cwd=PROJECT, check=True)
        # 预置一条只含安全元数据的失败作业，验证服务启动后的阶段恢复 API。
        jobs.mkdir(parents=True, exist_ok=True)
        (jobs / "smokefail001.json").write_text(json.dumps({
            "id": "smokefail001", "kind": "topic_map", "status": "failed",
            "created": time.time() - 10, "started": time.time() - 9,
            "finished": time.time() - 8, "rc": 1, "log": [],
            "stage": "构建会议脉络", "meeting": "_smoke",
            "queue_priority": 20, "priority_boost": False,
        }), encoding="utf-8")
        log_path = root / "server.log"
        fake_log_path = root / "fake-weknora.log"
        with log_path.open("w", encoding="utf-8") as log, \
                fake_log_path.open("w", encoding="utf-8") as fake_log:
            fake = subprocess.Popen(
                [str(PY), str(PROJECT / "web/tests/fake_weknora.py")],
                env=env, cwd=PROJECT, stdout=fake_log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            wait_ready(f"http://127.0.0.1:{weknora_port}", fake)
            proc = subprocess.Popen(
                [str(PY), str(PROJECT / "web/server.py")],
                env=env, cwd=PROJECT, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                wait_ready(base, proc)
                result = subprocess.run(
                    [str(PY), str(PROJECT / "web/tests/smoke_test.py")],
                    env=env, cwd=PROJECT,
                )
                if result.returncode:
                    time.sleep(0.2)
                    print("\n--- isolated server log (failure tail) ---", file=sys.stderr)
                    print(log_path.read_text(encoding="utf-8", errors="replace")[-12000:],
                          file=sys.stderr)
                return result.returncode
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=5)
                if fake.poll() is None:
                    os.killpg(fake.pid, signal.SIGTERM)
                    try:
                        fake.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(fake.pid, signal.SIGKILL)
                        fake.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
