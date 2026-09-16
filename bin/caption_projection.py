"""Deterministic caption cues shared by server, Web, and portable exports."""

from __future__ import annotations

import math
import re
import textwrap
from typing import Any

from person_display import display_revision, display_turn_speaker


PUNCTUATION = re.compile(r"(?<=[。！？!?；;，,.:：])\s*")
CJK = re.compile(r"[\u3400-\u9fff]")


def language_of(text: str) -> str:
    cjk = len(CJK.findall(text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return "mixed" if cjk and latin else "zh" if cjk else "en" if latin else "unknown"


def _chunks(text: str, duration: float) -> list[str]:
    text = " ".join(str(text or "").split())
    if not text:
        return []
    language = language_of(text)
    max_chars = 26 if language in {"zh", "mixed"} else 68
    pieces = [piece for piece in PUNCTUATION.split(text) if piece]
    chunks: list[str] = []
    for piece in pieces:
        while len(piece) > max_chars:
            cut = piece.rfind(" ", 0, max_chars + 1)
            cut = cut if cut > max_chars // 2 else max_chars
            chunks.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if piece:
            chunks.append(piece)
    wanted = max(len(chunks), math.ceil(max(0.0, duration) / 6.0))
    while len(chunks) < wanted:
        index = max(range(len(chunks)), key=lambda value: len(chunks[value]))
        piece = chunks.pop(index)
        cut = max(1, len(piece) // 2)
        space = piece.rfind(" ", 0, cut + 1)
        cut = space if space > 0 else cut
        chunks[index:index] = [piece[:cut].strip(), piece[cut:].strip()]
    return [piece for piece in chunks if piece]


def _word_cues(words: list[dict], start: float, end: float) -> list[tuple[float, float, str]]:
    valid = [{"start": max(start, float(word.get("start", start))),
              "end": min(end, float(word.get("end", word.get("start", start)))),
              "text": str(word.get("text") or word.get("word") or "").strip()}
             for word in words if str(word.get("text") or word.get("word") or "").strip()]
    rows, current = [], []
    for word in valid:
        current.append(word)
        duration = current[-1]["end"] - current[0]["start"]
        chars = sum(len(item["text"]) for item in current)
        punctuated = bool(re.search(r"[。！？!?；;，,.:：]$", word["text"]))
        if duration >= 1.2 and (duration >= 6 or chars >= 32 or punctuated):
            rows.append((current[0]["start"], current[-1]["end"], "".join(item["text"] for item in current)))
            current = []
    if current:
        rows.append((current[0]["start"], max(current[-1]["end"], current[0]["start"] + .1),
                     "".join(item["text"] for item in current)))
    return rows


def _split_translation(text: str, count: int) -> list[str]:
    chunks = _chunks(text, count * 3.0)
    if count <= 1:
        return [text] if text else [""]
    if len(chunks) == count:
        return chunks
    # Translation has no word timestamps. Distribute it over the whole source turn,
    # never dump a long turn into its first short cue and leave the rest blank.
    tokens = text.split() if " " in text else list(text)
    separator = " " if " " in text else ""
    return [separator.join(tokens[len(tokens) * i // count:len(tokens) * (i + 1) // count])
            for i in range(count)]


def readable_translation_cues(cues: list[dict]) -> list[dict]:
    """Two-line translation cards timed across the complete original utterance.

    These are reading timings, not forced word alignment. Never extend past the
    source utterance or drop text to achieve an impossible reading speed.
    """
    groups = []
    for cue in cues:
        key = cue.get("turn_id") or cue.get("cue_id")
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(cue)
    result = []
    for key, group in groups:
        parts = [str(c.get("translated_text") or "").strip() for c in group]
        text = " ".join(part for part in parts if part)
        if not text:
            continue
        width = 24 if language_of(text) in {"zh", "mixed"} else 40
        lines = textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)
        blocks = ["\n".join(lines[i:i + 2]) for i in range(0, len(lines), 2)]
        start, end = float(group[0]["start"]), float(group[-1]["end"])
        duration = max(.1, end - start)
        floor = min(2.0, duration / len(blocks))
        remaining = max(0, duration - floor * len(blocks))
        weight = sum(len(block) for block in blocks)
        cursor = start
        for index, block in enumerate(blocks):
            stop = end if index == len(blocks) - 1 else cursor + floor + remaining * len(block) / weight
            result.append({**group[0], "cue_id": f"{key}-EN{index + 1}",
                           "start": round(cursor, 3), "end": round(stop, 3),
                           "translated_text": block})
            cursor = stop
    return result


def build_cues(turns: list[dict[str, Any]], *, profiles: list[dict] | None = None,
               translation: dict | None = None, transcript_revision: str | None = None) -> list[dict]:
    profiles = profiles or []
    by_voice = {str(voice): profile for profile in profiles for voice in profile.get("voice_ids", [])}
    by_speaker = {str(profile.get("speaker")): profile for profile in profiles}
    translated = ({int(row.get("index")): str(row.get("translated_text") or "")
                   for row in translation.get("turns", [])}
                  if translation and translation.get("state") == "ready" else {})
    translation_revision = (translation or {}).get("source_revision") if translated else None
    revision = transcript_revision or (translation or {}).get("source_revision")
    cues = []
    for index, turn in enumerate(turns):
        start = max(0.0, float(turn.get("start") or 0))
        end = max(start + .1, float(turn.get("end") or start + .1))
        timed = _word_cues(turn.get("words") or [], start, end)
        if not timed:
            chunks = _chunks(str(turn.get("text") or ""), end - start)
            span = (end - start) / max(1, len(chunks))
            cursor = start
            timed = []
            for part in chunks:
                part_end = end if len(timed) == len(chunks) - 1 else cursor + span
                timed.append((cursor, max(cursor + .1, part_end), part))
                cursor = part_end
        translated_parts = _split_translation(translated.get(index, ""), len(timed))
        turn_id = str(turn.get("id") or f"T{index + 1:06d}")
        profile = by_voice.get(str(turn.get("voice") or "")) or by_speaker.get(str(turn.get("speaker") or "")) or {}
        for part_index, ((cue_start, cue_end, text), translated_text) in enumerate(zip(timed, translated_parts), 1):
            cues.append({"cue_id": f"{turn_id}-C{part_index:02d}", "turn_id": turn_id,
                         "start": round(cue_start, 3), "end": round(cue_end, 3),
                         "person_id": profile.get("person_id"),
                         "voice_id": turn.get("voice") or turn.get("voice_id"),
                         "source_speaker_label": str(turn.get("speaker") or "Unknown"),
                         "display_speaker": display_turn_speaker(turn, by_voice, by_speaker),
                         "original_text": text, "translated_text": translated_text or None,
                         "language": language_of(text), "transcript_revision": revision,
                         "translation_revision": translation_revision,
                         "display_revision": display_revision(profiles)})
    return cues


def _timestamp(seconds: float) -> str:
    millis = round(max(0.0, seconds) * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def render_vtt(cues: list[dict], *, mode: str = "source", speaker: str = "auto",
               content_type: str = "meeting") -> str:
    if mode not in {"source", "translation", "bilingual"}:
        raise ValueError("Unsupported caption mode")
    show_names = speaker == "show" or (speaker == "auto" and content_type == "meeting")
    rows = ["WEBVTT", ""]
    previous, previous_end = None, -99.0
    if mode == "translation":
        cues = readable_translation_cues(cues)
    for cue in cues:
        original, translated = str(cue.get("original_text") or ""), str(cue.get("translated_text") or "")
        if mode == "translation" and not translated:
            continue
        body = translated if mode == "translation" else original
        if mode == "bilingual" and translated:
            body = f"{original}\n{translated}"
        name = str(cue.get("display_speaker") or cue.get("source_speaker_label") or "Unknown")
        if show_names and (name != previous or cue["start"] - previous_end >= 12):
            body = f"{name}: {body}"
        body = body.replace("-->", "--\u200b>").replace("\x00", "")
        rows.extend([str(cue["cue_id"]), f"{_timestamp(cue['start'])} --> {_timestamp(cue['end'])}", body, ""])
        previous, previous_end = name, cue["end"]
    return "\n".join(rows)
