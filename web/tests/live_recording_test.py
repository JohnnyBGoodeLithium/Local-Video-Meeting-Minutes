#!/usr/bin/env python3
"""Synthetic media: recording survives analysis failure and preserves replay."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))
from meeting_core.live.recording import LiveRecording
from meeting_core.live.evidence import LiveEvidence
from meeting_core.live.store import LiveSessionStore
from meeting_core.live.runtime import HLSBackgroundWorker, LiveSessionManager
from meeting_core.live.source import ProbedLiveSource
from meeting_core.live.capabilities import LiveSourceCapabilities


def run(command, **kwargs):
    return subprocess.run(command, **kwargs)


with tempfile.TemporaryDirectory(prefix="live-recording-test-") as tmp:
    root = Path(tmp)
    source_file = root / "synthetic.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
        "color=c=blue:s=320x180:r=10", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000",
        "-t", "2.2", "-c:v", "libx264", "-preset", "ultrafast", "-g", "10", "-c:a", "aac",
        str(source_file)], check=True, timeout=20)
    rec = LiveRecording(root / "recorded")
    command = rec.begin(str(source_file))
    command[command.index("-segment_time") + 1] = "1"
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    assert "pipe:1" not in command
    added = rec.scan()
    assert len(added) >= 2
    assert rec.scan() == []
    before = [(s["file"], (rec.root / s["file"]).read_bytes()) for s in added]
    replay = rec.replay()
    assert replay and replay.stat().st_size > 0
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(replay)], capture_output=True, check=True)
    assert float(result.stdout) >= 2
    first_path = rec.root / added[0]["file"]
    original = first_path.read_bytes()
    first_path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    assert rec.replay() is None and rec.data["state"] == "segments_only"
    assert rec.data["gaps"][-1]["reason"] == "segment_integrity_failure"
    first_path.write_bytes(original)
    resumed = LiveRecording(root / "recorded")
    resumed.gap("service_restart")
    resumed.begin(str(source_file))
    assert all((resumed.root / name).read_bytes() == content for name, content in before)
    assert resumed.data["gaps"]

    store = LiveSessionStore(root / "evidence")
    store.initialize({}, {})
    calls = []
    evidence = LiveEvidence(store, summarize=lambda turns, frames: calls.append((turns, frames)) or "Synthetic topic")
    assert evidence.capture(rec.root / added[0]["file"], 0)
    assert not evidence.capture(rec.root / added[0]["file"], 1)
    assert evidence.capture(rec.root / added[-1]["file"], 31)
    evidence.update_topic([{"start": 0, "end": 65, "text": "Synthetic discussion"}], 65)
    assert len(calls) == 1 and len(calls[0][1]) == 2
    evidence.update_topic([], 66)
    assert len(calls) == 1
    assert evidence.topics["items"][0]["frames"]
    evidence.summarize = lambda *_: (_ for _ in ()).throw(RuntimeError("offline"))
    evidence.update_topic([], 130)
    assert evidence.topics["state"] == "unavailable" and evidence.topics["items"]
    assert len(store.read_jsonl("frame-events.jsonl")) == 2

    source = ProbedLiveSource("hls", "https://example.invalid/live.m3u8",
        LiveSourceCapabilities(native_video=True, native_audio=True, background_safe=True,
                               audio_capture_method="native_hls"),
        "https://example.invalid/live.m3u8", None, 1)
    release_asr = threading.Event()
    def unavailable_asr(**kwargs):
        release_asr.wait(10)
        raise RuntimeError("synthetic ASR failure")
    def local_capture(command, **kwargs):
        command = list(command)
        command[command.index("-i") + 1] = str(source_file)
        return subprocess.Popen(command, **kwargs)
    worker = HLSBackgroundWorker(source, root / "worker", content_type="media", mode="analyze_background",
        popen=local_capture, asr_provider_factory=unavailable_asr,
        fetch=lambda _: ("#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nseg.ts\n#EXT-X-ENDLIST\n", None))
    worker.start()
    assert worker.recording_done.wait(10), "ASR blocked recording"
    assert worker.capture_process.poll() == 0
    release_asr.set()
    worker.thread.join(15)
    assert not worker.thread.is_alive()
    assert worker.status()["state"] == "FAILED", "analysis failure must not become complete"
    assert worker.recording.data["replay"] == "source_video.mp4"
    assert (root / "worker/source_video.mp4").is_file()
    assert worker.workspace()["frames"]
    assert "media_playlist_url" not in json.dumps(worker.workspace())
    manager = LiveSessionManager()
    assert "worker" in manager.recover(root)
    restored = manager.get("worker")
    assert restored.recording_done.is_set()
    assert restored.workspace()["recording"]["replay"] == "source_video.mp4"

    # Manifest-only serving supports failed-analysis recordings, and rejects escape paths.
    sys.path.insert(0, str(ROOT / "web"))
    from unittest.mock import patch
    import os
    import deps
    from routers.live import live_asset
    from fastapi import HTTPException
    with patch.dict(os.environ, {"MEETING_LIVE_CONTEXT": "1"}), patch.object(deps, "MEETINGS", root):
        assert Path(live_asset("worker", "replay", "full").path).is_file()
        assert Path(live_asset("worker", "segment", "0").path).is_file()
        frame = worker.workspace()["frames"][0]
        assert Path(live_asset("worker", "frame", frame["id"]).path).is_file()
        for kind, identity in [("segment", "-1"), ("frame", "../../source.json"), ("other", "full")]:
            try:
                live_asset("worker", kind, identity)
            except HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError("unsafe or unsupported asset accepted")

print("live recording: real segments/replay/screenshots, restart retention, slow and failed ASR passed")
