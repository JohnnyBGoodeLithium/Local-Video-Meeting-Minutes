"""Deterministic presentation names over stable person/voice/turn identity."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def display_person(person: dict[str, Any] | None, *, native_name: str = "",
                   session_label: str = "Unknown") -> str:
    """Resolve a label without fuzzy binding or modifying identity data."""
    person = person or {}
    return str(person.get("display_name") or person.get("name")
               or native_name or session_label or "Unknown")


def display_turn_speaker(turn: dict[str, Any], profiles_by_voice: dict[str, dict] | None = None,
                         profiles_by_speaker: dict[str, dict] | None = None) -> str:
    voice = str(turn.get("voice") or turn.get("voice_id") or "")
    source = str(turn.get("speaker") or turn.get("source_speaker_label") or "Unknown")
    profile = (profiles_by_voice or {}).get(voice) or (profiles_by_speaker or {}).get(source) or {}
    return display_person(profile, native_name=str(profile.get("native_name") or ""),
                          session_label=source)


def display_revision(profiles: list[dict[str, Any]]) -> str:
    """A presentation-only revision; it never invalidates transcript semantics."""
    material = [{"person_id": row.get("person_id"),
                 "display_name": row.get("display_name"),
                 "voice_ids": sorted(row.get("voice_ids") or [])}
                for row in profiles]
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
