"""Chunked near-live ASR contracts and overlap reconciliation.

Existing batch ASR providers are not described as native streaming models.  The
live layer therefore treats each rolling chunk as an observation and keeps the
tail provisional until a later window makes it stable.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import re
import tempfile
from typing import Iterable, Protocol
import wave

from .models import TimedTextSignal


@dataclass(frozen=True, slots=True)
class ASRChunk:
    start: float
    end: float
    pcm: bytes
    sample_rate: int = 16000

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start or self.sample_rate <= 0:
            raise ValueError("invalid ASR chunk")


@dataclass(frozen=True, slots=True)
class ASRSegment:
    start: float
    end: float
    text: str
    provisional: bool = True


class NearLiveASRProvider(Protocol):
    name: str

    def transcribe_chunk(self, chunk: ASRChunk) -> list[ASRSegment]: ...


class ExistingASRProviderAdapter:
    """Run the existing local batch provider on one PCM rolling window."""

    def __init__(self, provider, *, language: str | None = None):
        self.provider = provider
        self.language = language
        self.name = f"chunked:{provider.name}"

    def transcribe_chunk(self, chunk: ASRChunk) -> list[ASRSegment]:
        with tempfile.NamedTemporaryFile(prefix="live-asr-", suffix=".wav") as temp:
            with wave.open(temp.name, "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(chunk.sample_rate)
                handle.writeframes(chunk.pcm)
            result = self.provider.transcribe(
                audio=temp.name, language=self.language, return_time_stamps=True)[0]
        stamps = getattr(result, "time_stamps", None) or []
        if stamps:
            def field(item, name):
                return item[name] if isinstance(item, dict) else getattr(item, name)
            return [ASRSegment(
                chunk.start + float(field(item, "start_time")),
                chunk.start + float(field(item, "end_time")),
                str(field(item, "text")), True,
            ) for item in stamps if str(field(item, "text")).strip()]
        text = str(getattr(result, "text", "")).strip()
        return [ASRSegment(chunk.start, chunk.end, text, True)] if text else []


class ChunkedNearLiveASR:
    def __init__(self, provider: NearLiveASRProvider):
        self.provider = provider
        self.transcript = NearLiveTranscript()

    def process(self, chunk: ASRChunk) -> list[ASRSegment]:
        observations = self.provider.transcribe_chunk(chunk)
        return self.transcript.ingest(observations, stable_before=chunk.start)


def _tokens(text: str) -> list[str]:
    words = re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE)
    return words if len(words) > 1 else list(text)


def merge_overlap_text(left: str, right: str, *, minimum: int = 1) -> str:
    """Merge repeated suffix/prefix tokens without rewriting either observation."""
    left, right = left.strip(), right.strip()
    if not left:
        return right
    if not right or right in left:
        return left
    if left in right:
        return right
    a, b = _tokens(left), _tokens(right)
    for size in range(min(len(a), len(b)), minimum - 1, -1):
        if [item.casefold() for item in a[-size:]] == [item.casefold() for item in b[:size]]:
            if re.search(r"\s", left + right):
                return " ".join(a + b[size:]).replace(" .", ".").replace(" ,", ",")
            return "".join(a + b[size:])
    return f"{left} {right}".strip()


class NearLiveTranscript:
    """Accumulate rolling ASR observations with stable/provisional boundaries."""

    def __init__(self):
        self.segments: list[ASRSegment] = []

    def ingest(self, observations: Iterable[ASRSegment], *, stable_before: float) \
            -> list[ASRSegment]:
        for item in observations:
            text = " ".join(item.text.split()).strip()
            if not text or item.end <= item.start:
                continue
            current = ASRSegment(float(item.start), float(item.end), text, True)
            if self.segments and current.start <= self.segments[-1].end:
                previous = self.segments.pop()
                current = ASRSegment(
                    start=min(previous.start, current.start), end=max(previous.end, current.end),
                    text=merge_overlap_text(previous.text, current.text), provisional=True,
                )
            self.segments.append(current)
        self.segments = [replace(item, provisional=item.end > stable_before)
                         for item in self.segments]
        return list(self.segments)

    def signals(self, *, language: str | None = None) -> list[TimedTextSignal]:
        output = []
        for index, item in enumerate(self.segments):
            raw = f"asr\0{index}\0{item.start:.3f}\0{item.end:.3f}\0{item.text}"
            output.append(TimedTextSignal(
                id=f"L{hashlib.sha256(raw.encode()).hexdigest()[:16]}",
                start=item.start, end=item.end, text=item.text, speaker=None,
                text_source="local_asr", speaker_source="unknown", language=language,
                provisional=item.provisional, review_needed=True,
            ))
        return output


class RollingChunkPlanner:
    def __init__(self, chunk_seconds: float, overlap_seconds: float):
        if chunk_seconds <= 0 or overlap_seconds < 0 or overlap_seconds >= chunk_seconds:
            raise ValueError("invalid rolling chunk configuration")
        self.chunk_seconds = chunk_seconds
        self.overlap_seconds = overlap_seconds

    def windows(self, duration: float) -> list[tuple[float, float]]:
        windows = []
        start = 0.0
        while start < duration:
            end = min(duration, start + self.chunk_seconds)
            windows.append((round(start, 6), round(end, 6)))
            if end >= duration:
                break
            start = end - self.overlap_seconds
        return windows
