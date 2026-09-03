"""Conservative public-source probing for Experimental Live Context."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .capabilities import LiveSourceCapabilities
from .hls import (HLSError, HLSMasterPlaylist, HLSMediaPlaylist, parse_master_playlist,
                  parse_media_playlist, sanitized_url)


MAX_PROBE_BYTES = 2 * 1024 * 1024


class SourceProbeError(RuntimeError):
    """A source is unsafe, unavailable, authenticated, or unsupported."""


def validate_public_url(url: str,
                        resolve: Callable[..., list] = socket.getaddrinfo) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SourceProbeError("source must be a public HTTP(S) URL")
    if parsed.username or parsed.password:
        raise SourceProbeError("credentials in source URLs are unsupported")
    try:
        addresses = {item[4][0] for item in resolve(
            parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
                                                     type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise SourceProbeError("source hostname cannot be resolved") from exc
    if not addresses:
        raise SourceProbeError("source hostname cannot be resolved")
    for raw in addresses:
        address = ipaddress.ip_address(raw)
        if (not address.is_global or address.is_private or address.is_loopback
                or address.is_link_local or address.is_reserved):
            raise SourceProbeError("private or local source addresses are unsupported")
    return url.strip()


class _PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class PublicSourceFetcher:
    def __init__(self, *, timeout: float = 10):
        self.timeout = timeout
        self.opener = build_opener(_PublicRedirects())

    def __call__(self, url: str) -> tuple[str, str | None]:
        validate_public_url(url)
        request = Request(url, headers={
            "User-Agent": "Local-Meeting-Minutes-Live-Context/experimental",
            "Accept": "application/vnd.apple.mpegurl, application/x-mpegURL, text/plain;q=0.8",
        })
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                length = response.headers.get("Content-Length")
                if length and int(length) > MAX_PROBE_BYTES:
                    raise SourceProbeError("source probe response is too large")
                payload = response.read(MAX_PROBE_BYTES + 1)
                if len(payload) > MAX_PROBE_BYTES:
                    raise SourceProbeError("source probe response is too large")
                return payload.decode("utf-8", errors="replace"), response.headers.get_content_type()
        except SourceProbeError:
            raise
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise SourceProbeError("source requires authentication") from exc
            raise SourceProbeError("source probe failed") from exc
        except (OSError, URLError, ValueError) as exc:
            raise SourceProbeError("source probe failed") from exc


@dataclass(frozen=True, slots=True)
class ProbedLiveSource:
    source_kind: str
    source_url: str
    capabilities: LiveSourceCapabilities
    media_playlist_url: str | None = None
    subtitle_playlist_url: str | None = None
    target_duration: float = 6.0

    def public_dict(self) -> dict:
        return {
            "source_kind": self.source_kind,
            "display_url": sanitized_url(self.source_url),
            "capabilities": self.capabilities.to_dict(),
        }


def probe_live_source(url: str, *, fetch: Callable[[str], tuple[str, str | None]] | None = None,
                      validate: bool = True) -> ProbedLiveSource:
    if validate:
        validate_public_url(url)
    parsed = urlsplit(url)
    looks_hls = parsed.path.lower().endswith(".m3u8")
    if not looks_hls:
        return ProbedLiveSource(
            "web_player", url,
            LiveSourceCapabilities(
                browser_required=True, authentication_required=False,
                background_safe=False, browser_background_safe=None,
                audio_capture_method="unavailable", subtitle_method="visual_caption",
                end_detection=("media_element", "live_ui", "live_to_vod"),
            ),
        )
    fetcher = fetch or PublicSourceFetcher()
    raw, _content_type = fetcher(url)
    if "#EXT-X-STREAM-INF" in raw or "#EXT-X-MEDIA:" in raw:
        try:
            master: HLSMasterPlaylist = parse_master_playlist(raw, url)
        except HLSError as exc:
            raise SourceProbeError("invalid HLS master playlist") from exc
        media_url = master.variants[0] if master.variants else (
            master.audio[0].uri if master.audio else None)
        subtitle_url = master.subtitles[0].uri if master.subtitles else None
        capabilities = LiveSourceCapabilities(
            native_video=bool(master.variants), native_audio=bool(master.audio or master.variants),
            native_subtitle=bool(subtitle_url), browser_required=False,
            background_safe=True, audio_capture_method="native_hls",
            subtitle_method="native_hls" if subtitle_url else "local_asr",
            end_detection=("hls_endlist", "media_sequence", "media_progress"),
        )
        return ProbedLiveSource("hls", url, capabilities, media_url, subtitle_url)
    try:
        media: HLSMediaPlaylist = parse_media_playlist(raw, url)
    except (HLSError, ValueError) as exc:
        raise SourceProbeError("invalid HLS media playlist") from exc
    capabilities = LiveSourceCapabilities(
        native_video=True, native_audio=True, native_subtitle=False,
        browser_required=False, background_safe=not media.drm_detected,
        audio_capture_method="native_hls", subtitle_method="local_asr",
        drm_detected=media.drm_detected,
        end_detection=("hls_endlist", "media_sequence", "media_progress"),
    )
    return ProbedLiveSource("hls", url, capabilities, url, None, media.target_duration)
