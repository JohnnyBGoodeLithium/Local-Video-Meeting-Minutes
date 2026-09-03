#!/usr/bin/env python3
"""Benchmark rolling chunk sizes against the configured local ASR provider.

The JSON output contains timings only; recognized text is never printed or
written. Run this locally with approved audio, never in hosted CI.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import wave

from meeting_core.asr import create_provider
from meeting_core.live.asr import ASRChunk, ExistingASRProviderAdapter, RollingChunkPlanner
from meeting_core.live.metrics import benchmark_summary


def read_pcm(path: Path) -> tuple[bytes, int, float]:
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise ValueError("benchmark input must be 16-bit mono WAV")
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
        return frames, rate, handle.getnframes() / float(rate)


def benchmark(path: Path, chunk_sizes: list[float], overlap: float,
              language: str | None = None) -> list[dict]:
    pcm, rate, duration = read_pcm(path)
    provider = ExistingASRProviderAdapter(
        create_provider(with_aligner=True), language=language)
    sample_bytes = 2
    results = []
    for size in chunk_sizes:
        planner = RollingChunkPlanner(size, min(overlap, size / 2))
        lags, backlogs = [], []
        total_wall = 0.0
        for start, end in planner.windows(duration):
            first, last = round(start * rate) * sample_bytes, round(end * rate) * sample_bytes
            chunk = ASRChunk(start, end, pcm[first:last], rate)
            began = time.monotonic()
            provider.transcribe_chunk(chunk)
            elapsed = time.monotonic() - began
            total_wall += elapsed
            lags.append(elapsed)
            backlogs.append(max(0.0, elapsed - (end - start)))
        result = benchmark_summary(
            duration=duration, wall_seconds=total_wall, asr_lag=lags,
            audio_backlog=backlogs, dropped_audio_chunks=0)
        result.update({"chunk_seconds": size, "overlap_seconds": min(overlap, size / 2),
                       "provider": provider.name})
        results.append(result)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark chunked near-live ASR")
    parser.add_argument("wav", type=Path)
    parser.add_argument("--chunk-sizes", default="5,8,12,15")
    parser.add_argument("--overlap", type=float, default=1.0)
    parser.add_argument("--language")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        sizes = [float(value) for value in args.chunk_sizes.split(",")]
        results = benchmark(args.wav, sizes, args.overlap, args.language)
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    payload = json.dumps({"schema": "live-asr-benchmark/v1", "results": results},
                         ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
