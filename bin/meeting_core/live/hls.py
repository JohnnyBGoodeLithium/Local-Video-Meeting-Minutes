"""Generic, token-safe HLS playlist parsing and sliding-window tracking."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

from .models import TimedTextSignal
from .signals import generic_subtitle_signals
from .vtt import parse_webvtt_text


class HLSError(RuntimeError):
    """An HLS source is invalid, unavailable, or protected."""


def sanitized_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _attributes(value: str) -> dict[str, str]:
    result = {}
    for match in re.finditer(r'(?:^|,)([A-Z0-9-]+)=("(?:[^"\\]|\\.)*"|[^,]*)', value):
        item = match.group(2).strip()
        result[match.group(1)] = item[1:-1] if item.startswith('"') and item.endswith('"') else item
    return result


@dataclass(frozen=True, slots=True)
class HLSRendition:
    kind: str
    uri: str
    language: str | None = None
    name: str | None = None
    group_id: str | None = None


@dataclass(frozen=True, slots=True)
class HLSMasterPlaylist:
    variants: tuple[str, ...]
    audio: tuple[HLSRendition, ...]
    subtitles: tuple[HLSRendition, ...]


@dataclass(frozen=True, slots=True)
class HLSSegment:
    sequence: int
    uri: str
    duration: float | None = None


@dataclass(frozen=True, slots=True)
class HLSMediaPlaylist:
    media_sequence: int
    target_duration: float
    segments: tuple[HLSSegment, ...]
    endlist: bool
    drm_detected: bool


def parse_master_playlist(raw: str, base_url: str) -> HLSMasterPlaylist:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    variants: list[str] = []
    audio: list[HLSRendition] = []
    subtitles: list[HLSRendition] = []
    expect_variant = False
    for line in lines:
        if line.startswith("#EXT-X-STREAM-INF:"):
            expect_variant = True
            continue
        if expect_variant and not line.startswith("#"):
            variants.append(urljoin(base_url, line))
            expect_variant = False
            continue
        if not line.startswith("#EXT-X-MEDIA:"):
            continue
        attrs = _attributes(line.split(":", 1)[1])
        kind = attrs.get("TYPE", "").lower()
        uri = attrs.get("URI")
        if kind not in {"audio", "subtitles"} or not uri:
            continue
        rendition = HLSRendition(
            kind=kind, uri=urljoin(base_url, uri), language=attrs.get("LANGUAGE"),
            name=attrs.get("NAME"), group_id=attrs.get("GROUP-ID"),
        )
        (audio if kind == "audio" else subtitles).append(rendition)
    if not variants and not audio and not subtitles:
        raise HLSError("HLS master playlist has no playable renditions")
    return HLSMasterPlaylist(tuple(variants), tuple(audio), tuple(subtitles))


def parse_media_playlist(raw: str, base_url: str) -> HLSMediaPlaylist:
    if "#EXTM3U" not in raw:
        raise HLSError("invalid HLS playlist")
    sequence = 0
    target = 6.0
    pending_duration: float | None = None
    segments: list[HLSSegment] = []
    drm = False
    for line in (item.strip() for item in raw.splitlines()):
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            sequence = int(line.split(":", 1)[1])
        elif line.startswith("#EXT-X-TARGETDURATION:"):
            target = max(0.5, float(line.split(":", 1)[1]))
        elif line.startswith("#EXTINF:"):
            pending_duration = float(line.split(":", 1)[1].split(",", 1)[0])
        elif line.startswith("#EXT-X-KEY:"):
            method = _attributes(line.split(":", 1)[1]).get("METHOD", "")
            drm = method.upper() not in {"", "NONE"}
        elif line and not line.startswith("#"):
            segments.append(HLSSegment(sequence + len(segments), urljoin(base_url, line),
                                       pending_duration))
            pending_duration = None
    return HLSMediaPlaylist(sequence, target, tuple(segments),
                            "#EXT-X-ENDLIST" in raw, drm)


class HLSPlaylistTracker:
    """Consume each media sequence once and expose checkpoint state."""

    def __init__(self, consumed_sequence: int | None = None):
        self.consumed_sequence = consumed_sequence
        self.failures = 0

    def consume(self, playlist: HLSMediaPlaylist) -> tuple[HLSSegment, ...]:
        if playlist.drm_detected:
            raise HLSError("DRM-protected HLS is unsupported")
        fresh = tuple(segment for segment in playlist.segments
                      if self.consumed_sequence is None
                      or segment.sequence > self.consumed_sequence)
        if fresh:
            self.consumed_sequence = fresh[-1].sequence
        self.failures = 0
        return fresh

    def checkpoint(self) -> dict[str, int | None]:
        return {"consumed_sequence": self.consumed_sequence}

    def poll(self, url: str, fetch: Callable[[str], str]) -> tuple[tuple[HLSSegment, ...],
                                                                    HLSMediaPlaylist | None]:
        try:
            raw = fetch(url)
            playlist = parse_media_playlist(raw, url)
            return self.consume(playlist), playlist
        except HLSError:
            raise
        except Exception:
            # Callers expose only the exception class and sanitized_url(url), never query tokens.
            self.failures += 1
            return (), None


class HLSSubtitleSource:
    """Consume new WebVTT subtitle segments without skipping failed downloads."""

    def __init__(self, consumed_sequence: int | None = None):
        self.consumed_sequence = consumed_sequence

    def consume_playlist(self, raw: str, playlist_url: str,
                         fetch: Callable[[str], str]) -> tuple[list[TimedTextSignal],
                                                              HLSMediaPlaylist]:
        playlist = parse_media_playlist(raw, playlist_url)
        if playlist.drm_detected:
            raise HLSError("DRM-protected HLS is unsupported")
        output: list[TimedTextSignal] = []
        for segment in playlist.segments:
            if self.consumed_sequence is not None and segment.sequence <= self.consumed_sequence:
                continue
            try:
                body = fetch(segment.uri)
                cues = parse_webvtt_text(body)
            except Exception:
                # Stop at the gap. A later poll retries this exact sequence before newer ones.
                break
            output.extend(generic_subtitle_signals(
                cues, namespace=f"hls-subtitle:{segment.sequence}"))
            self.consumed_sequence = segment.sequence
        return output, playlist

    def checkpoint(self) -> dict[str, int | None]:
        return {"consumed_sequence": self.consumed_sequence}
