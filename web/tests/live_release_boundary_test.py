#!/usr/bin/env python3
"""Live runtime data and model weights stay outside the application bundle."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from build_release_bundle import forbidden_reason


for path in (
    "models/pyannote/model.safetensors",
    "bin/meeting_core/live/model.pt",
    "meetings/synthetic/.live/text-signals.jsonl",
    "recordings/inbox/live.ts",
):
    assert forbidden_reason(path), path

assert forbidden_reason("bin/meeting_core/live/models.py") is None

print("live release boundary tests: OK")
