#!/usr/bin/env python3
"""逐字稿翻译的优先批次、部分结果、取消与续跑（全虚构、无模型调用）。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "web"))
import translation_service as translation  # noqa: E402


with tempfile.TemporaryDirectory(prefix="translation-service-test-") as tmp:
    mdir = Path(tmp) / "meetings" / "synthetic"
    mdir.mkdir(parents=True)
    turns = [
        {
            "speaker": "Synthetic Speaker",
            "start": float(i),
            "end": float(i + 1),
            "text": (f"Synthetic English turn {i}." if i % 2
                     else f"虚构中文轮次{i}。"),
        }
        for i in range(25)
    ]
    source = json.dumps(turns, ensure_ascii=False, indent=1)
    (mdir / "transcript.spk.json").write_text(source, encoding="utf-8")
    progress_rows = []
    cancel = {"value": False}

    def on_progress(done: int, total: int) -> None:
        if done:
            document = json.loads(translation.sidecar_path(mdir).read_text(encoding="utf-8"))
            progress_rows.append([item["index"] for item in document.get("turns", [])])
            cancel["value"] = True

    try:
        translation.translate_transcript(
            mdir, "Synthetic Meeting", {}, dry_run=True,
            priority_indexes=lambda: [22], on_progress=on_progress,
            should_cancel=lambda: cancel["value"])
        raise AssertionError("expected cancellation")
    except translation.TranslationCancelled:
        pass

    partial = translation.translation_payload(mdir, "Synthetic Meeting", {})
    assert partial["state"] == "cancelled"
    assert partial["translated"] == 5
    assert progress_rows[0] == [20, 21, 22, 23, 24]
    assert (mdir / "transcript.spk.json").read_text(encoding="utf-8") == source

    resumed_progress = []
    completed = translation.translate_transcript(
        mdir, "Synthetic Meeting", {}, dry_run=True,
        on_progress=lambda done, total: resumed_progress.append((done, total)),
        should_cancel=lambda: False)
    assert resumed_progress[0] == (5, 25)
    assert completed["status"] == "complete"
    assert len(completed["turns"]) == 25
    assert translation.translation_payload(mdir, "Synthetic Meeting", {})["state"] == "ready"

print("Transcript translation: priority, partial cancel, and resume passed")
