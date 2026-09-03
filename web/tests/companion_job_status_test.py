#!/usr/bin/env python3
"""Companion job projection excludes commands, files and raw logs."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "web"), str(ROOT / "bin")]
import companion_projection as projection  # noqa: E402


raw = {"id": "synthetic001", "status": "running", "kind": "upload", "route": "video",
       "display_name": "Synthetic media", "created": 1, "cmd": ["/private/path", "--secret"],
       "files": ["private.mp4"], "log": ["private transcript"],
       "progress": {"schema": "job-progress/v2", "state": "running", "phase": "speech_processing",
                    "message_key": "progress.speech_processing", "done": 2, "total": 4,
                    "unit": "items", "available_outputs": {"transcript": "partial"},
                    "phases": []}}
value = projection.job(raw, [raw])
encoded = json.dumps(value)
assert value["can_review"] is True and value["done"] == 2
assert "private/path" not in encoded and "private transcript" not in encoded
assert set(value) == {"id", "title", "status", "content_type", "created_at",
                      "what_is_happening", "phase", "done", "total", "unit",
                      "estimated_remaining", "ready", "can_review"}
print("companion job status: safe job-progress/v2 projection passed")
