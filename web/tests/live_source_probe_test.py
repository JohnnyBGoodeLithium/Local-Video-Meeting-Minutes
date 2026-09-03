#!/usr/bin/env python3
"""Public live source probing is token-safe and rejects local network targets."""

import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.source import SourceProbeError, probe_live_source, validate_public_url


def global_resolve(host, port, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", port))]

assert validate_public_url("https://example.invalid/live", resolve=global_resolve).endswith("/live")

def local_resolve(host, port, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

try:
    validate_public_url("http://localhost/live", resolve=local_resolve)
except SourceProbeError:
    pass
else:
    raise AssertionError("local source URL accepted")

master = """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",URI="audio.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",URI="captions.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=1000,AUDIO="audio",SUBTITLES="subs"
video.m3u8
"""
source = probe_live_source(
    "https://example.invalid/live/master.m3u8?token=private",
    fetch=lambda _url: (master, "application/vnd.apple.mpegurl"), validate=False)
assert source.source_kind == "hls"
assert source.capabilities.background_safe is True
assert source.capabilities.native_subtitle is True
assert source.media_playlist_url.endswith("/live/video.m3u8")
assert "token=" not in source.public_dict()["display_url"]

web = probe_live_source("https://example.invalid/watch?id=private", validate=False)
assert web.source_kind == "web_player"
assert web.capabilities.browser_required is True
assert web.capabilities.background_safe is False

print("live source probe tests: OK")
