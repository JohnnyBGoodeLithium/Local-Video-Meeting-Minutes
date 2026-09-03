"""Resolve local-only model installations without network fallback."""

from __future__ import annotations

import os
from pathlib import Path


class ModelNotInstalledError(RuntimeError):
    """A required local runtime pack has not been installed."""


def pyannote_candidates(application_root: Path, *, environ=None, home: Path | None = None) \
        -> list[Path]:
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    candidates = []
    configured = str(environ.get("MEETING_PYANNOTE_MODEL") or "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(Path(application_root) / "models" / "pyannote" /
                      "speaker-diarization-community-1")
    candidates.append(home / ".local" / "share" / "models" / "hf" / "pyannote" /
                      "speaker-diarization-community-1")
    return candidates


def resolve_pyannote_model(application_root: Path, *, environ=None,
                           home: Path | None = None) -> Path:
    for candidate in pyannote_candidates(application_root, environ=environ, home=home):
        path = candidate.resolve()
        if path.is_dir():
            return path
    raise ModelNotInstalledError(
        "Speaker model is not installed locally. Install the verified diarization runtime "
        "pack under models/pyannote/speaker-diarization-community-1 or set "
        "MEETING_PYANNOTE_MODEL. No model was downloaded."
    )
