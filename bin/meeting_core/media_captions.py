"""Conservative, subtitle-first inputs for public video imports.

Only demonstrably original-language WebVTT is eligible. Extractor dictionaries,
signed URLs and request headers are transient; persistence uses an explicit
provenance whitelist. Caption authorship is not human review or speaker identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import ipaddress
import math
import os
from pathlib import Path
import re
import socket
import tempfile
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from .live.models import TimedTextSignal
from .live.signals import generic_subtitle_signals
from .live.vtt import WebVTTCue, WebVTTError, parse_webvtt_text, timestamp_seconds


SCHEMA = "media-captions/v1"
SELECTION_POLICY = "original_human_then_automatic_then_asr"
MAX_CAPTION_BYTES = 16 * 1024 * 1024
MAX_CANDIDATES = 8
MAX_CUES = 100_000
ROLLUP_WINDOW = 2048
REASONS = frozenset({
    "no_captions", "original_language_unknown", "original_language_conflict",
    "no_original_captions", "translated_only", "unsupported_format",
    "captions_unusable", "candidate_limit", "download_failed", "invalid_download",
    "caption_too_large", "invalid_encoding", "invalid_header", "empty_captions",
    "invalid_timing", "media_timing_mismatch", "unsupported_timestamps",
    "too_many_cues", "unsafe_caption_url", "unsupported_protocol",
    "caption_read_failed", "user_requested_asr",
})
_LANGUAGE = re.compile(r"[a-z]{2,3}(?:-[a-z0-9]{2,8}){0,3}\Z")
_TIMING = re.compile(
    r"(?P<start>(?:\d{1,3}:)?\d{2}:\d{2}\.\d{3})[ \t]+-->[ \t]+"
    r"(?P<end>(?:\d{1,3}:)?\d{2}:\d{2}\.\d{3})(?:[ \t]+[^\n]*)?\Z"
)
_VOICE_TAG = re.compile(r"</?v(?:[.\s][^>]*)?>", re.I)


class CaptionError(ValueError):
    """A stable, shareable reason; never include downloader error contents."""

    def __init__(self, reason: str):
        self.reason = reason if reason in REASONS else "captions_unusable"
        super().__init__(self.reason)


def normalize_language(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower().replace("_", "-")
    if value.endswith("-orig"):
        value = value[:-5]
    if not _LANGUAGE.fullmatch(value) or value.split("-")[0] in {"und", "mul", "zxx"}:
        return None
    return value


def _same_language(left: str, right: str) -> bool:
    left_parts, right_parts = left.split("-"), right.split("-")
    if left_parts[0] != right_parts[0]:
        return False
    left_script = next((part for part in left_parts[1:] if len(part) == 4 and part.isalpha()), None)
    right_script = next((part for part in right_parts[1:] if len(part) == 4 and part.isalpha()), None)
    # A generic language can match a more specific tag; explicit conflicting
    # scripts cannot be silently converted into canonical original-language text.
    return not (left_script and right_script and left_script != right_script)


def _iso_time(value) -> str | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        return stamp.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (ValueError, OverflowError):
        return None


def project_caption_provenance(value) -> dict:
    """Project only bounded, typed metadata suitable for a shareable source."""
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        return {}
    output = {"schema": SCHEMA, "selection_policy": SELECTION_POLICY}
    enums = {
        "source": {"native_subtitle", "local_asr"},
        "kind": {"human", "automatic"},
        "language_evidence": {"metadata", "original_track", "unknown", "conflict"},
        "timestamp_source": {"subtitle_cues", "asr"},
        "selection_reason": {"original_human", "original_automatic", "asr_fallback"},
        "fallback_reason": REASONS,
        "format": {"vtt"},
    }
    for key, allowed in enums.items():
        item = value.get(key)
        if isinstance(item, str) and item in allowed:
            output[key] = item
    for key in ("language", "original_language"):
        language = normalize_language(value.get(key))
        if language:
            output[key] = language
    stamp = _iso_time(value.get("imported_at"))
    if stamp:
        output["imported_at"] = stamp
    for key, maximum in (("cue_count", MAX_CUES), ("raw_bytes", MAX_CAPTION_BYTES)):
        number = value.get(key)
        if type(number) is int and 0 <= number <= maximum:
            output[key] = number
    digest = value.get("raw_sha256")
    if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
        output["raw_sha256"] = digest
    attempts = value.get("attempts")
    if isinstance(attempts, list):
        output["attempts"] = []
        for attempt in attempts[:MAX_CANDIDATES]:
            if not isinstance(attempt, dict):
                continue
            projected = project_caption_provenance({"schema": SCHEMA, **{
                key: attempt[key] for key in ("kind", "language", "format", "raw_sha256", "raw_bytes")
                if key in attempt
            }})
            projected.pop("schema")
            projected.pop("selection_policy")
            if attempt.get("status") in ("selected", "rejected"):
                projected["status"] = attempt["status"]
            reason = attempt.get("reason")
            if isinstance(reason, str) and reason in REASONS:
                projected["reason"] = reason
            if attempt.get("raw_truncated") is True:
                projected["raw_truncated"] = True
            output["attempts"].append(projected)
    return output


@dataclass(frozen=True, slots=True)
class CaptionCandidate:
    kind: str
    language: str
    ext: str
    url: str = field(default="", repr=False)
    headers: dict = field(default_factory=dict, repr=False)
    inline_data: str | bytes | None = field(default=None, repr=False)
    protocol: str = field(default="", repr=False)


@dataclass(frozen=True, slots=True)
class CaptionPreparation:
    cues: tuple[WebVTTCue, ...]
    raw_path: Path | None
    provenance: dict

    @property
    def usable(self) -> bool:
        return bool(self.cues and self.raw_path)

    def signals(self) -> list[TimedTextSignal]:
        signals = generic_subtitle_signals(
            self.cues, namespace="media-caption", language=self.provenance.get("language"))
        review = "automatic" if self.provenance.get("kind") == "automatic" else "platform_provided"
        return [replace(signal, text_review_status=review, review_needed=True) for signal in signals]


def _translated(track: dict, language: str | None = None) -> bool:
    if any(track.get(key) is True for key in ("is_translated", "translated", "is_translation")):
        return True
    name = str(track.get("name") or "").lower()
    if "translated" in name or "translation" in name:
        return True
    source_language = normalize_language(track.get("source_language"))
    declared_language = normalize_language(track.get("language"))
    if declared_language and language and not _same_language(declared_language, language):
        return True
    language = language or declared_language
    if source_language and language and not _same_language(source_language, language):
        return True
    try:
        return bool(parse_qs(urlsplit(str(track.get("url") or "")).query).get("tlang"))
    except ValueError:
        return True


def _tracks(info: dict):
    for group, kind in (("subtitles", "human"), ("automatic_captions", "automatic")):
        entries = info.get(group)
        if not isinstance(entries, dict):
            continue
        for key, formats in entries.items():
            language = normalize_language(key)
            if not language or not isinstance(formats, list):
                continue
            for track in formats:
                if isinstance(track, dict):
                    yield str(key), language, kind, track


def _caption_plan(info: dict) -> tuple[list[CaptionCandidate], dict, str | None]:
    tracks = list(_tracks(info))
    metadata = normalize_language(info.get("original_language")) or normalize_language(info.get("language"))
    original_tracks = {
        language for key, language, _, track in tracks
        if (key.lower().endswith("-orig") or track.get("is_original") is True)
        and not _translated(track, language)
    }
    evidence = "metadata" if metadata else "original_track" if original_tracks else "unknown"
    original = metadata or (sorted(original_tracks)[0] if original_tracks else None)
    base = {"language_evidence": evidence}
    if original:
        base["original_language"] = original
    if original and any(not _same_language(original, other) for other in original_tracks):
        base["language_evidence"] = "conflict"
        return [], base, "original_language_conflict"
    if not tracks:
        return [], base, "no_captions"
    if not original:
        return [], base, "original_language_unknown"
    candidates = []
    original_formats = []
    for key, language, kind, track in tracks:
        if not _same_language(original, language) or _translated(track, language):
            continue
        original_formats.append(track)
        if str(track.get("ext") or "").lower() != "vtt":
            continue
        headers = {}
        for source in (info.get("http_headers"), track.get("http_headers")):
            if isinstance(source, dict):
                headers.update({key: value for key, value in source.items()
                                if isinstance(key, str) and isinstance(value, str)})
        candidates.append(CaptionCandidate(
            kind=kind, language=language, ext="vtt", url=str(track.get("url") or ""),
            headers=headers, inline_data=track.get("data"), protocol=str(track.get("protocol") or ""),
        ))
    candidates.sort(key=lambda item: (item.kind != "human", item.language != original))
    if candidates:
        unique = []
        seen = set()
        for candidate in candidates:
            inline = candidate.inline_data if isinstance(candidate.inline_data, (str, bytes)) else None
            key = (candidate.kind, candidate.url, inline, candidate.protocol, tuple(sorted(candidate.headers.items())))
            if key not in seen:
                seen.add(key)
                unique.append(candidate)
        return unique, base, None
    reason = ("unsupported_format" if original_formats else
              "translated_only" if all(_translated(track, language) for _, language, _, track in tracks)
              else "no_original_captions")
    return [], base, reason


def _bounded_candidates(candidates: list[CaptionCandidate]) -> list[CaptionCandidate]:
    """Reserve automatic fallback capacity; repeated human failures cannot starve it."""
    if len(candidates) <= MAX_CANDIDATES:
        return candidates
    human = [item for item in candidates if item.kind == "human"]
    automatic = [item for item in candidates if item.kind == "automatic"]
    human_budget = min(len(human), max(MAX_CANDIDATES // 2, MAX_CANDIDATES - len(automatic)))
    return human[:human_budget] + automatic[:MAX_CANDIDATES - human_budget]


def _suffix_overlap(left: str, right: str) -> int:
    # Captions are untrusted. A prefix-function scan is linear in a bounded
    # roll-up window; enormous cues must not cause quadratic suffix slicing.
    limit = min(len(left), len(right), ROLLUP_WINDOW)
    if limit < 3:
        return 0
    window = right[:limit] + "\x00" + left[-limit:]
    prefix = [0] * len(window)
    for index in range(1, len(window)):
        match = prefix[index - 1]
        while match and window[index] != window[match]:
            match = prefix[match - 1]
        if window[index] == window[match]:
            match += 1
        prefix[index] = match
    non_ascii_prefix = next((index for index, char in enumerate(right[:limit]) if ord(char) <= 127), limit)
    size = prefix[-1]
    while size >= 3:
        # Latin words must overlap at boundaries; unspaced scripts need at least
        # four matching characters. No fuzzy spelling or punctuation edits.
        before = left[len(left) - size - 1] if len(left) > size else ""
        after = right[size:size + 1]
        boundary = (not before or not before.isalnum()) and (not after or not after.isalnum())
        if boundary or 4 <= size <= non_ascii_prefix:
            return size
        size = prefix[size - 1]
    return 0


def _deduplicate(cues: list[WebVTTCue]) -> tuple[WebVTTCue, ...]:
    output: list[WebVTTCue] = []
    previous: WebVTTCue | None = None
    for cue in cues:
        text = cue.text
        if previous and cue.start < previous.end and output:
            if text == previous.text or previous.text.startswith(text):
                output[-1] = replace(output[-1], end=max(output[-1].end, cue.end))
                previous = cue
                continue
            overlap = _suffix_overlap(previous.text, text)
            if overlap:
                text = text[overlap:].strip()
        if text:
            output.append(WebVTTCue(cue.start, cue.end, text, speaker=None))
        previous = cue
    return tuple(output)


def parse_caption_bytes(raw: bytes, *, ext: str = "vtt", duration: float | None = None
                        ) -> tuple[WebVTTCue, ...]:
    """Strict validation around the shared parser; keep only cue-level timing.

    Reject partial malformed timing instead of silently dropping bad spans. Raw
    bytes remain separate and unchanged; de-duplication affects normalized cues.
    """
    if ext.lower().lstrip(".") != "vtt":
        raise CaptionError("unsupported_format")
    if not isinstance(raw, bytes):
        raise CaptionError("invalid_download")
    if len(raw) > MAX_CAPTION_BYTES:
        raise CaptionError("caption_too_large")
    try:
        body = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError as exc:
        raise CaptionError("invalid_encoding") from exc
    if "\x00" in body:
        raise CaptionError("invalid_encoding")
    first = body.split("\n", 1)[0]
    if not re.fullmatch(r"WEBVTT(?:[ \t].*)?", first):
        raise CaptionError("invalid_header")
    if re.search(r"(?m)^X-TIMESTAMP-MAP\s*=", body):
        raise CaptionError("unsupported_timestamps")
    try:
        duration = float(duration) if duration is not None else None
    except (ValueError, TypeError):
        duration = None
    if duration is not None and (not math.isfinite(duration) or duration <= 0):
        duration = None
    count = 0
    last_start = -1.0
    for block in re.split(r"\n\s*\n", body):
        if re.match(r"^(?:NOTE|STYLE|REGION)(?:\s|$)", block.lstrip()):
            continue
        timing_lines = [line for line in block.splitlines() if "-->" in line]
        if len(timing_lines) > 1:
            raise CaptionError("invalid_timing")
        if not timing_lines and block.strip() and not block.startswith("WEBVTT"):
            raise CaptionError("invalid_timing")
        for line in block.splitlines():
            if "-->" not in line:
                continue
            timing = _TIMING.fullmatch(line.strip())
            if not timing:
                raise CaptionError("invalid_timing")
            for timestamp in (timing["start"], timing["end"]):
                parts = timestamp.split(":")
                if float(parts[-1]) >= 60 or int(parts[-2]) >= 60:
                    raise CaptionError("invalid_timing")
            start, end = timestamp_seconds(timing["start"]), timestamp_seconds(timing["end"])
            if end <= start or start < last_start:
                raise CaptionError("invalid_timing")
            if duration is not None and (start >= duration or end > duration + 1.0):
                raise CaptionError("media_timing_mismatch")
            last_start = start
            count += 1
            if count > MAX_CUES:
                raise CaptionError("too_many_cues")
    if not count:
        raise CaptionError("empty_captions")
    try:
        # Strip only voice markup before calling the shared parser, so a cue
        # with multiple <v> spans retains every span without importing identity.
        cues = parse_webvtt_text(_VOICE_TAG.sub("", body))
    except (WebVTTError, ValueError) as exc:
        raise CaptionError("empty_captions") from exc
    return _deduplicate(cues)


def parse_caption_file(path: Path, *, duration: float | None = None) -> tuple[WebVTTCue, ...]:
    path = Path(path)
    with path.open("rb") as stream:
        raw = stream.read(MAX_CAPTION_BYTES + 1)
    return parse_caption_bytes(raw, ext=path.suffix, duration=duration)


def _write_raw(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".caption-", delete=False) as temp:
        temporary = Path(temp.name)
        temp.write(raw)
        temp.flush()
        os.fsync(temp.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_captions(info: dict, destination: Path, fetch: Callable[[CaptionCandidate], bytes], *,
                     imported_at: str | None = None) -> CaptionPreparation:
    """Try original human tracks, then original automatic tracks, then ASR.

    Invalid downloaded bytes are kept in bounded, private attempt-N.vtt files.
    Oversized results retain only a clearly marked prefix, whose hash describes
    that saved prefix. Network errors are reduced to stable reason codes.
    """
    info = info if isinstance(info, dict) else {}
    destination = Path(destination)
    candidates, language_info, reason = _caption_plan(info)
    provenance = {
        "schema": SCHEMA, "selection_policy": SELECTION_POLICY,
        "source": "local_asr", "selection_reason": "asr_fallback",
        "timestamp_source": "asr", "attempts": [], **language_info,
        "imported_at": _iso_time(imported_at) or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    attempts = _bounded_candidates(candidates)
    limited_human = (sum(item.kind == "human" for item in attempts) <
                     sum(item.kind == "human" for item in candidates))
    for index, candidate in enumerate(attempts, start=1):
        attempt = {"kind": candidate.kind, "language": candidate.language,
                   "format": candidate.ext, "status": "rejected"}
        provenance["attempts"].append(attempt)
        try:
            raw = fetch(candidate)
        except Exception as exc:
            attempt["reason"] = exc.reason if isinstance(exc, CaptionError) else "download_failed"
            continue
        if not isinstance(raw, bytes):
            attempt["reason"] = "invalid_download"
            continue
        saved = raw[:MAX_CAPTION_BYTES]
        _write_raw(destination / f"attempt-{index}.vtt", saved)
        attempt.update(raw_sha256=hashlib.sha256(saved).hexdigest(), raw_bytes=len(saved))
        if len(raw) > MAX_CAPTION_BYTES:
            attempt.update(reason="caption_too_large", raw_truncated=True)
            continue
        try:
            cues = parse_caption_bytes(raw, ext=candidate.ext, duration=info.get("duration"))
        except CaptionError as exc:
            attempt["reason"] = exc.reason
            continue
        path = destination / "source.vtt"
        _write_raw(path, raw)
        attempt["status"] = "selected"
        provenance.update(
            source="native_subtitle", kind=candidate.kind, language=candidate.language,
            timestamp_source="subtitle_cues", selection_reason=f"original_{candidate.kind}",
            cue_count=len(cues), raw_sha256=attempt["raw_sha256"], raw_bytes=len(raw), format="vtt",
        )
        if candidate.kind == "automatic" and limited_human:
            provenance["fallback_reason"] = "candidate_limit"
        return CaptionPreparation(cues, path, project_caption_provenance(provenance))
    provenance["fallback_reason"] = reason or (
        "candidate_limit" if len(candidates) > MAX_CANDIDATES else "captions_unusable")
    return CaptionPreparation((), None, project_caption_provenance(provenance))


def _validate_public_caption_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise CaptionError("unsafe_caption_url")
        if parsed.username is not None or parsed.password is not None:
            raise CaptionError("unsafe_caption_url")
        host = parsed.hostname.rstrip(".").lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal")):
            raise CaptionError("unsafe_caption_url")
        addresses = {entry[4][0] for entry in socket.getaddrinfo(host, parsed.port)}
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise CaptionError("unsafe_caption_url")
    except (ValueError, OSError) as exc:
        raise CaptionError("unsafe_caption_url") from exc
    return value


def build_ytdlp_caption_fetcher(downloader, *, validate_url: Callable[[str], str] | None = None
                               ) -> Callable[[CaptionCandidate], bytes]:
    """Use the existing yt-dlp session, without writing its extractor metadata.

    The initial caption URL receives the public-URL policy; redirects and DNS
    resolution otherwise have the same transport boundary as media downloads.
    HLS/fragmented subtitles require separate timing reconciliation and fall back.
    """
    validate = validate_url or _validate_public_caption_url

    def fetch(candidate: CaptionCandidate) -> bytes:
        if isinstance(candidate.inline_data, bytes):
            return candidate.inline_data[:MAX_CAPTION_BYTES + 1]
        if isinstance(candidate.inline_data, str):
            return candidate.inline_data.encode("utf-8")[:MAX_CAPTION_BYTES + 1]
        if candidate.protocol not in {"", "http", "https"}:
            raise CaptionError("unsupported_protocol")
        try:
            url = validate(candidate.url)
        except Exception as exc:
            raise CaptionError("unsafe_caption_url") from exc
        from yt_dlp.networking import Request

        response = downloader.urlopen(Request(url, headers=candidate.headers))
        try:
            chunks = []
            remaining = MAX_CAPTION_BYTES + 1
            while remaining:
                chunk = response.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            return b"".join(chunks)
        finally:
            response.close()

    return fetch
