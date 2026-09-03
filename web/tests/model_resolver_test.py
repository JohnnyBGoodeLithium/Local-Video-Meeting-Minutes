#!/usr/bin/env python3
"""Pyannote resolution is local-only and follows the documented priority."""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.model_resolver import (ModelNotInstalledError, pyannote_candidates,
                                         resolve_pyannote_model)


with tempfile.TemporaryDirectory(prefix="mm-model-resolver-") as tmp:
    root = Path(tmp) / "application"
    home = Path(tmp) / "home"
    configured = Path(tmp) / "configured"
    app_local = root / "models" / "pyannote" / "speaker-diarization-community-1"
    user_local = home / ".local/share/models/hf/pyannote/speaker-diarization-community-1"
    candidates = pyannote_candidates(root, environ={}, home=home)
    assert candidates == [app_local, user_local]
    user_local.mkdir(parents=True)
    assert resolve_pyannote_model(root, environ={}, home=home) == user_local.resolve()
    app_local.mkdir(parents=True)
    assert resolve_pyannote_model(root, environ={}, home=home) == app_local.resolve()
    configured.mkdir()
    assert resolve_pyannote_model(
        root, environ={"MEETING_PYANNOTE_MODEL": str(configured)}, home=home) \
        == configured.resolve()

with tempfile.TemporaryDirectory(prefix="mm-model-missing-") as tmp:
    try:
        resolve_pyannote_model(Path(tmp) / "app", environ={}, home=Path(tmp) / "home")
    except ModelNotInstalledError as exc:
        assert "not installed locally" in str(exc)
        assert "No model was downloaded" in str(exc)
    else:
        raise AssertionError("missing model did not produce a setup error")

print("model resolver tests: OK")
