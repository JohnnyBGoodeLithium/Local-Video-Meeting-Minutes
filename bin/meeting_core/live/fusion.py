"""Deterministic reconciliation of provisional text and speaker observations."""

from __future__ import annotations

from difflib import SequenceMatcher

from .models import TimedTextSignal


TEXT_PRIORITY = {
    "local_asr": 1,
    "ocr_caption": 2,
    "native_subtitle": 3,
    "native_transcript": 4,
}


def _overlap(left: TimedTextSignal, right: TimedTextSignal) -> float:
    return max(0.0, min(left.end, right.end) - max(left.start, right.start))


def _same_observation(left: TimedTextSignal, right: TimedTextSignal) -> bool:
    shortest = max(0.1, min(left.end - left.start, right.end - right.start))
    temporal = _overlap(left, right) / shortest
    textual = SequenceMatcher(None, left.text.casefold(), right.text.casefold()).ratio()
    return temporal >= 0.5 and textual >= 0.55


def fuse_text_signals(signals: list[TimedTextSignal]) -> tuple[list[dict], list[dict]]:
    """Choose stronger duplicate sources while retaining a provenance audit."""
    selected: list[TimedTextSignal] = []
    provenance: list[dict] = []
    ordered = sorted(signals, key=lambda item: (item.start, item.end,
                                                -TEXT_PRIORITY[item.text_source], item.id))
    for signal in ordered:
        duplicate = next((item for item in selected if _same_observation(item, signal)), None)
        if duplicate is None:
            selected.append(signal)
            provenance.append({"selected": signal.id, "observed": [signal.id]})
            continue
        if TEXT_PRIORITY[signal.text_source] > TEXT_PRIORITY[duplicate.text_source]:
            index = selected.index(duplicate)
            selected[index] = signal
            record = next(item for item in provenance if item["selected"] == duplicate.id)
            record["observed"].append(signal.id)
            record["selected"] = signal.id
        else:
            record = next(item for item in provenance if item["selected"] == duplicate.id)
            record["observed"].append(signal.id)

    selected.sort(key=lambda item: (item.start, item.end, item.id))
    turns = []
    for signal in selected:
        speaker = signal.speaker or "未具名"
        item = {"speaker": speaker, "start": round(signal.start, 3),
                "end": round(signal.end, 3), "text": signal.text}
        if (turns and turns[-1]["speaker"] == speaker
                and item["start"] - turns[-1]["end"] <= 1.0):
            turns[-1]["end"] = max(turns[-1]["end"], item["end"])
            turns[-1]["text"] = f"{turns[-1]['text']} {item['text']}".strip()
        else:
            turns.append(item)
    return turns, provenance
