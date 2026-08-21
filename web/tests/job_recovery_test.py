#!/usr/bin/env python3
"""失败恢复只使用安全元数据，并严格区分可续跑与必须重导入的阶段。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT / "web"), str(PROJECT / "bin")]

with tempfile.TemporaryDirectory(prefix="meeting-recovery-") as tmp:
    root = Path(tmp)
    os.environ["MEETING_DATA_ROOT"] = str(root)
    os.environ["MEETING_WEB_JOBS"] = str(root / "jobs")

    from job_recovery import recovery_plan  # noqa: E402

    meeting = root / "meetings" / "synthetic"
    meeting.mkdir(parents=True)
    (meeting / "transcript.spk.json").write_text("[]", encoding="utf-8")
    (meeting / "transcript.txt").write_text("synthetic fixture", encoding="utf-8")
    (meeting / "minutes.md").write_text("# Synthetic", encoding="utf-8")
    (meeting / "slides.json").write_text("[]", encoding="utf-8")
    (meeting / "audio.wav").write_bytes(b"fictional protected audio")
    (meeting / "source_video.mp4").write_bytes(b"fictional protected video")
    (meeting / "stamps.json").write_text(
        '{"language":"English","text":"synthetic","time_stamps":[]}', encoding="utf-8")

    base = {"status": "failed", "meeting": "synthetic", "log": [], "rc": 1}
    late = recovery_plan({**base, "kind": "upload", "stage": "理解共享画面"})
    assert late["state"] == "available" and late["mode"] == "minutes"
    assert late["scope"] == "minutes" and "transcript" in late["retained"]
    assert "visual_cache" in late["retained"] and late["schema"] == "job-recovery/v1"

    early = recovery_plan({**base, "kind": "upload", "stage": "语音转写"})
    assert early["state"] == "available" and early["action"] == "resume_from_asr"
    assert early["mode"] == "speaker_resume" and "asr_timestamps" in early["retained"]

    (meeting / "stamps.json").unlink()
    no_checkpoint = recovery_plan({**base, "kind": "upload", "stage": "语音转写"})
    assert no_checkpoint["state"] == "manual" and no_checkpoint["action"] == "reimport"
    (meeting / "stamps.json").write_text(
        '{"language":"English","text":"synthetic","time_stamps":[]}', encoding="utf-8")

    topic = recovery_plan({**base, "kind": "topic_map", "stage": "构建会议脉络"})
    assert topic["state"] == "available" and topic["mode"] == "topic_map"

    translated = recovery_plan({**base, "kind": "translation",
                                "translation_artifact": "minutes",
                                "target_language": "en"})
    assert translated["state"] == "available" and translated["mode"] == "translation"

    retranscribe = recovery_plan({**base, "kind": "retranscribe", "stage": "语音转写"})
    assert retranscribe["state"] == "available" and retranscribe["mode"] == "retranscribe"

    resource = recovery_plan({**base, "kind": "regen", "stage": "生成纪要",
                              "rc": 137, "log": ["[error] 子进程失败 (rc=137)"]})
    assert resource["category"] == "resource" and resource["state"] == "available"

    missing = recovery_plan({**base, "kind": "regen", "meeting": "missing"})
    assert missing["state"] == "manual" and not missing["retained"]

print("Job recovery: stage scope, retained assets, and failure classes passed")
