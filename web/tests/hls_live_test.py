#!/usr/bin/env python3
"""Generic HLS master/sliding playlist behavior uses synthetic fixtures."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.hls import (HLSError, HLSPlaylistTracker, HLSSubtitleSource,
                                   parse_master_playlist, parse_media_playlist, sanitized_url)


master = parse_master_playlist("""#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="English",LANGUAGE="en",URI="audio/live.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",LANGUAGE="en",URI="subs/live.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=800000,AUDIO="aud",SUBTITLES="subs"
video/live.m3u8
""", "https://example.invalid/event/master.m3u8?token=private")
assert master.variants == ("https://example.invalid/event/video/live.m3u8",)
assert master.audio[0].language == "en"
assert master.subtitles[0].uri.endswith("/event/subs/live.m3u8")

first = parse_media_playlist("""#EXTM3U
#EXT-X-TARGETDURATION:4
#EXT-X-MEDIA-SEQUENCE:101
#EXTINF:4.0,
seg101.ts?token=secret
#EXTINF:4.0,
seg102.ts?token=secret
""", "https://example.invalid/live/index.m3u8?session=secret")
tracker = HLSPlaylistTracker()
assert [item.sequence for item in tracker.consume(first)] == [101, 102]
assert tracker.checkpoint() == {"consumed_sequence": 102}

sliding = parse_media_playlist("""#EXTM3U
#EXT-X-TARGETDURATION:4
#EXT-X-MEDIA-SEQUENCE:102
#EXTINF:4.0,
seg102.ts
#EXTINF:4.0,
seg103.ts
#EXT-X-ENDLIST
""", "https://example.invalid/live/index.m3u8")
assert [item.sequence for item in tracker.consume(sliding)] == [103]
assert sliding.endlist is True and sliding.target_duration == 4

assert sanitized_url("https://example.invalid/live.m3u8?token=secret") == \
       "https://example.invalid/live.m3u8"

items, playlist = tracker.poll("https://example.invalid/live.m3u8?token=secret",
                               lambda _url: (_ for _ in ()).throw(TimeoutError()))
assert items == () and playlist is None and tracker.failures == 1

protected = parse_media_playlist("""#EXTM3U
#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key"
#EXT-X-MEDIA-SEQUENCE:1
#EXTINF:4,
one.ts
""", "https://example.invalid/live.m3u8")
try:
    tracker.consume(protected)
except HLSError:
    pass
else:
    raise AssertionError("protected HLS must be rejected")

subtitle_playlist = """#EXTM3U
#EXT-X-TARGETDURATION:4
#EXT-X-MEDIA-SEQUENCE:7
#EXTINF:4,
sub7.vtt
#EXTINF:4,
sub8.vtt
"""
subtitle_bodies = {
    "https://example.invalid/live/sub7.vtt":
        "WEBVTT\n\n00:00:28.000 --> 00:00:30.000\nFirst live cue.\n",
    "https://example.invalid/live/sub8.vtt":
        "WEBVTT\n\n00:00:32.000 --> 00:00:34.000\nSecond live cue.\n",
}
subtitle_source = HLSSubtitleSource()
subtitle_signals, subtitle_state = subtitle_source.consume_playlist(
    subtitle_playlist, "https://example.invalid/live/subtitles.m3u8",
    subtitle_bodies.__getitem__)
assert [item.start for item in subtitle_signals] == [28.0, 32.0]
assert all(item.text_source == "native_subtitle" and item.provisional
           for item in subtitle_signals)
assert subtitle_source.checkpoint() == {"consumed_sequence": 8}
assert subtitle_state.endlist is False

# A temporary failure must not advance past the missing sequence.
retry_source = HLSSubtitleSource()
signals, _ = retry_source.consume_playlist(
    subtitle_playlist, "https://example.invalid/live/subtitles.m3u8",
    lambda uri: subtitle_bodies[uri] if uri.endswith("sub7.vtt")
    else (_ for _ in ()).throw(TimeoutError()))
assert len(signals) == 1 and retry_source.consumed_sequence == 7
signals, _ = retry_source.consume_playlist(
    subtitle_playlist, "https://example.invalid/live/subtitles.m3u8",
    subtitle_bodies.__getitem__)
assert len(signals) == 1 and signals[0].start == 32.0

print("HLS live tests: OK")
