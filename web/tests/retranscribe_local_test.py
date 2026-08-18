#!/usr/bin/env python3
"""本地重转写快照/恢复边界：只用临时目录和虚构文本，不调模型。"""

import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))
import retranscribe_local as local_asr  # noqa: E402


with tempfile.TemporaryDirectory(prefix="meeting-local-asr-") as temporary:
    data_root = Path(temporary)
    mdir = data_root / "meetings" / "2026-01-02_Fictional-Review"
    mdir.mkdir(parents=True)
    os.environ["MEETING_DATA_ROOT"] = str(data_root)
    (mdir / "source_video.mp4").write_bytes(b"protected fictional video")
    (mdir / "source.docx").write_bytes(b"protected fictional transcript")
    (mdir / "source.json").write_text('{"transcript_source":"external"}', encoding="utf-8")
    (mdir / "transcript.spk.json").write_text('[{"text":"before"}]', encoding="utf-8")
    (mdir / "minutes.md").write_text("# Before", encoding="utf-8")
    (mdir / "samples").mkdir()
    (mdir / "samples" / "voice.wav").write_bytes(b"sample-before")

    managed = local_asr._managed_meeting(mdir)
    version, existing = local_asr._snapshot(managed)
    assert version.is_dir() and (version / "manifest.json").is_file()
    (mdir / "transcript.spk.json").write_text('[{"text":"partial"}]', encoding="utf-8")
    (mdir / "minutes.md").write_text("# Partial", encoding="utf-8")
    (mdir / "diarization.json").write_text("[]", encoding="utf-8")
    (mdir / "samples" / "voice.wav").write_bytes(b"sample-partial")
    local_asr._restore(mdir, version, existing)

    assert (mdir / "transcript.spk.json").read_text(encoding="utf-8") == '[{"text":"before"}]'
    assert (mdir / "minutes.md").read_text(encoding="utf-8") == "# Before"
    assert not (mdir / "diarization.json").exists()
    assert (mdir / "samples" / "voice.wav").read_bytes() == b"sample-before"
    assert (mdir / "source_video.mp4").read_bytes() == b"protected fictional video"
    assert (mdir / "source.docx").read_bytes() == b"protected fictional transcript"

print("local retranscription snapshot/restore boundary passed")
