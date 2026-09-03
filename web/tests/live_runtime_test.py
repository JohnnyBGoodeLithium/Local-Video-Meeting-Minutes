#!/usr/bin/env python3
"""A native-HLS worker continues independently and finalizes through existing stages."""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.capabilities import LiveSourceCapabilities
from meeting_core.live.runtime import HLSBackgroundWorker
from meeting_core.live.source import ProbedLiveSource


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
    assert (meeting / "transcript.spk.json").is_file()
    assert all("--autoplay" not in part for part in worker.capture_process.command)

print("live runtime tests: OK")
