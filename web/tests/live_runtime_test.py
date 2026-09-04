#!/usr/bin/env python3
"""A native-HLS worker continues independently and finalizes through existing stages."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.capabilities import LiveSourceCapabilities
import meeting_core.live.runtime as live_runtime
from meeting_core.live.runtime import HLSBackgroundWorker, LiveSessionManager
from meeting_core.live.source import ProbedLiveSource
from meeting_core.live.store import LiveSessionStore


class FakeProcess:
    def __init__(self, command, **_kwargs):
        self.command = command
        self.stdout = None
        self._returncode = None

    def poll(self):
        return self._returncode

    def terminate(self):
        self._returncode = 0

    def kill(self):
        self._returncode = -9

    def wait(self, timeout=None):
        self._returncode = 0 if self._returncode is None else self._returncode
        return self._returncode


media = """#EXTM3U
#EXT-X-TARGETDURATION:1
#EXT-X-MEDIA-SEQUENCE:4
#EXTINF:1,
segment.ts
#EXT-X-ENDLIST
"""
subtitle = """#EXTM3U
#EXT-X-TARGETDURATION:1
#EXT-X-MEDIA-SEQUENCE:9
#EXTINF:1,
caption.vtt
#EXT-X-ENDLIST
"""
vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nSynthetic live text.\n"

def fetch(url):
    if url.endswith("media.m3u8"):
        return media, "application/vnd.apple.mpegurl"
    if url.endswith("subtitles.m3u8"):
        return subtitle, "application/vnd.apple.mpegurl"
    if url.endswith("caption.vtt"):
        return vtt, "text/vtt"
    raise AssertionError(url)

with tempfile.TemporaryDirectory(prefix="mm-live-runtime-") as tmp:
    meeting = Path(tmp) / "meetings" / "live-synthetic"
    source = ProbedLiveSource(
        "hls", "https://example.invalid/master.m3u8",
        LiveSourceCapabilities(
            native_video=True, native_audio=True, native_subtitle=True,
            background_safe=True, audio_capture_method="native_hls",
            subtitle_method="native_hls", end_detection=("hls_endlist",)),
        "https://example.invalid/media.m3u8",
        "https://example.invalid/subtitles.m3u8", 1,
    )
    worker = HLSBackgroundWorker(
        source, meeting, content_type="media", mode="analyze_background",
        fetch=fetch, popen=FakeProcess, dry_run=True, sleep=lambda _seconds: None)
    worker.start()
    worker.thread.join(timeout=5)
    assert not worker.thread.is_alive()
    status = worker.status()
    assert status["state"] == "COMPLETE" and status["text_signals"] == 1
    workspace = worker.workspace()
    assert workspace["schema"] == "meeting-live-workspace/v1"
    assert workspace["transcript"]["total_turns"] == 1
    assert workspace["transcript"]["turns"][0]["text"] == "Synthetic live text."
    assert workspace["source"]["display_url"] == "https://example.invalid/master.m3u8"
    assert "media_playlist_url" not in json.dumps(workspace)
    assert workspace["takeaways"]["state"] == "deferred_until_finalize"
    assert (meeting / "transcript.spk.json").is_file()
    assert all("--autoplay" not in part for part in worker.capture_process.command)
    stored_source = json.loads((meeting / ".live" / "source.json").read_text())
    assert stored_source["resolved_from_page"] is False

with tempfile.TemporaryDirectory(prefix="mm-live-page-recovery-") as tmp:
    meetings = Path(tmp) / "meetings"
    meeting = meetings / "live-page-synthetic"
    store = LiveSessionStore(meeting)
    store.initialize(
        {"id": meeting.name, "content_type": "media", "mode": "analyze_background"},
        {
            "type": "hls",
            "url": "https://example.invalid/watch/live-event",
            "media_playlist_url": "https://media.example.invalid/expired.m3u8?token=old",
            "subtitle_playlist_url": None,
            "resolved_from_page": True,
            "capabilities": source.capabilities.to_dict(),
        },
    )
    store.save_checkpoint({"state": "LIVE", "media_time": 2, "text_signals": 0})
    refreshed = ProbedLiveSource(
        "hls", "https://example.invalid/watch/live-event", source.capabilities,
        "https://media.example.invalid/fresh.m3u8?token=new", None, 6, True)
    original_probe = live_runtime.probe_live_source
    manager = LiveSessionManager()
    started = []
    try:
        live_runtime.probe_live_source = lambda url: refreshed
        manager.start_hls = lambda chosen, *_args, **_kwargs: started.append(chosen)
        recovered = manager.recover(meetings, dry_run=True)
    finally:
        live_runtime.probe_live_source = original_probe
    assert recovered == [meeting.name]
    assert started and started[0].media_playlist_url.endswith("fresh.m3u8?token=new")

print("live runtime tests: OK")
