#!/usr/bin/env python3
"""转写落盘与 stamps 断点恢复只使用虚构文本，不调用模型。"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))

from transcribe import write_transcript_outputs  # noqa: E402


with tempfile.TemporaryDirectory(prefix="transcribe-output-") as temp_name:
    root = Path(temp_name)
    wav = root / "synthetic.wav"
    wav.write_bytes(b"fictional-audio-placeholder")
    stamps = [
        {"text": "Hello. ", "start_time": 0.0, "end_time": 0.7},
        {"text": "测试。", "start_time": 0.7, "end_time": 1.4},
    ]
    paragraphs, span = write_transcript_outputs(
        root, wav.stem, "English", "Hello. 测试。", stamps)
    rendered = (root / "transcript.ts.md").read_text(encoding="utf-8")
    assert paragraphs == 1 and span == (0.0, 1.4)
    assert "> 语言: English" in rendered and "Qwen3-ASR" in rendered

    # 删除两个确定性投影后，从已保存的 stamps 恢复；不得加载 ASR。
    (root / "transcript.ts.md").unlink()
    (root / "transcript.txt").unlink()
    completed = subprocess.run(
        [sys.executable, str(PROJECT / "bin" / "transcribe.py"), str(wav),
         "--out", str(root), "--reuse-stamps"],
        cwd=PROJECT, capture_output=True, text=True,
    )
    assert completed.returncode == 0
    assert "复用已完成 ASR" in completed.stdout
    assert json.loads((root / "stamps.json").read_text(encoding="utf-8"))["language"] == "English"
    assert (root / "transcript.ts.md").is_file() and (root / "transcript.txt").is_file()

print("Transcript outputs: language metadata and saved-stamps recovery passed")
