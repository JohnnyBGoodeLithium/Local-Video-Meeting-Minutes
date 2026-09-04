#!/usr/bin/env python3
"""Public live source probing is token-safe and rejects local network targets."""

import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.source import (
    SourceProbeError,
    probe_live_source,
    resolve_live_webpage,
    validate_public_url,
)


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

web = probe_live_source(
    "https://example.invalid/watch?id=private", validate=False, webpage_resolver=None)
assert web.source_kind == "web_player"
assert web.capabilities.browser_required is True
assert web.capabilities.background_safe is False

page_url = "https://example.invalid/room?session=private"
resolved_url = "https://media.example.invalid/live/index.m3u8?token=private"
assert resolve_live_webpage(
    page_url,
    extract=lambda _url: {
        "is_live": True,
        "live_status": "is_live",
        "protocol": "m3u8_native",
        "url": resolved_url,
    },
    resolve=global_resolve,
) == resolved_url

resolved = probe_live_source(
    page_url,
    fetch=lambda _url: ("#EXTM3U\n#EXT-X-TARGETDURATION:6\n", "application/x-mpegURL"),
    validate=False,
    webpage_resolver=lambda _url: resolved_url,
)
assert resolved.source_kind == "hls"
assert resolved.source_url == page_url
assert resolved.resolved_from_page is True
assert resolved.capabilities.native_audio is True
assert resolved.capabilities.background_safe is True
assert resolved.media_playlist_url == resolved_url
assert "token=" not in resolved.public_dict()["display_url"]
assert "session=" not in resolved.public_dict()["display_url"]

assert resolve_live_webpage(
    page_url,
    extract=lambda _url: {
        "is_live": False,
        "live_status": "was_live",
        "protocol": "m3u8_native",
        "url": resolved_url,
    },
    resolve=global_resolve,
) is None

assert resolve_live_webpage(
    page_url,
    extract=lambda _url: {
        "is_live": True,
        "live_status": "is_live",
        "protocol": "https",
        "url": "https://media.example.invalid/video.mp4",
    },
    resolve=global_resolve,
) is None

print("live source probe tests: OK")
