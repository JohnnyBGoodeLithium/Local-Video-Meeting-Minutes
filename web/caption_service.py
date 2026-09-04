"""Thin caption projection service over canonical turns and revision-bound translations."""

from pathlib import Path

import caption_projection
import meeting_artifact
import translation_service


def payload(mdir: Path, title: str, evidence: dict, bank_dir: Path,
            target: str) -> tuple[dict, list[dict]]:
    try:
        import json
        turns = json.loads((Path(mdir) / "transcript.spk.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        turns = []
    profiles = meeting_artifact.load_speaker_profiles(turns, bank_dir)
    translation = translation_service.translation_payload(
        Path(mdir), title, evidence, target=target)
    cues = caption_projection.build_cues(
        turns, profiles=profiles, translation=translation,
        transcript_revision=translation.get("source_revision"))
    return translation, cues
