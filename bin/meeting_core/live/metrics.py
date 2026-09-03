"""Metadata-only live metrics and replay benchmark summaries."""

from __future__ import annotations

import math
from typing import Iterable


METRIC_KEYS = {
    "audio_backlog_seconds",
    "asr_lag_seconds",
    "speaker_lag_seconds",
    "subtitle_lag_seconds",
    "caption_lag_seconds",
    "vl_lag_seconds",
    "dropped_audio_chunks",
    "processed_audio_seconds",
    "wall_seconds",
    "rtf",
    "speaker_cluster_churn",
    "speaker_reassignment",
    "peak_memory_bytes",
}


def percentile(values: Iterable[float], quantile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be within 0..1")
    index = (len(ordered) - 1) * quantile
    lower, upper = math.floor(index), math.ceil(index)
    if lower == upper:
        return round(ordered[lower], 3)
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 3)


class LiveMetrics:
    def __init__(self):
        self.values: dict[str, list[float]] = {key: [] for key in METRIC_KEYS}

    def record(self, key: str, value: float) -> None:
        if key not in METRIC_KEYS:
            raise ValueError("metric key is not metadata-safe")
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0:
            raise ValueError("metric value must be a finite non-negative number")
        self.values[key].append(numeric)

    def latest(self) -> dict[str, float]:
        return {key: values[-1] for key, values in self.values.items() if values}


def benchmark_summary(*, duration: float, wall_seconds: float,
                      asr_lag: Iterable[float] = (), speaker_lag: Iterable[float] = (),
                      caption_lag: Iterable[float] = (), vl_lag: Iterable[float] = (),
                      audio_backlog: Iterable[float] = (), dropped_audio_chunks: int = 0,
                      peak_memory_bytes: int | None = None) -> dict:
    if duration <= 0 or wall_seconds < 0:
        raise ValueError("invalid benchmark duration")
    backlog = list(audio_backlog)
    output = {
        "duration": round(duration, 3),
        "wall_seconds": round(wall_seconds, 3),
        "rtf": round(wall_seconds / duration, 4),
        "asr_lag_p50": percentile(asr_lag, 0.5),
        "asr_lag_p95": percentile(asr_lag, 0.95),
        "speaker_lag_p50": percentile(speaker_lag, 0.5),
        "speaker_lag_p95": percentile(speaker_lag, 0.95),
        "caption_lag_p50": percentile(caption_lag, 0.5),
        "caption_lag_p95": percentile(caption_lag, 0.95),
        "vl_lag_p50": percentile(vl_lag, 0.5),
        "vl_lag_p95": percentile(vl_lag, 0.95),
        "max_audio_backlog": round(max(backlog), 3) if backlog else 0.0,
        "dropped_audio_chunks": int(dropped_audio_chunks),
    }
    if peak_memory_bytes is not None:
        output["peak_memory_bytes"] = int(peak_memory_bytes)
    return output
