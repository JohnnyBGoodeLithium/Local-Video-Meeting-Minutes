#!/usr/bin/env python3
"""使用当前 ASR provider 重建已有会议，并在覆盖前创建可恢复快照。

原始音视频和 source.vtt/source.docx 始终保留；只重建逐字稿、说话人归属、
纪要、证据与会议脉络。视频会议复用已有屏幕逻辑页和 VL 解读缓存。

stdout 只打印元数据，不打印会议正文。
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path

from meeting_core.progress_events import phase_done, progress as progress_event


ROOT = Path(__file__).resolve().parent.parent
PY = Path(os.environ.get("MEETING_PYTHON", sys.executable)).expanduser()

CORE_FILES = {
    "source.json", "transcript.txt", "transcript.json", "transcript.md",
    "transcript.spk.json", "transcript.spk.md", "stamps.json", "segments.json",
    "diarization.json", "minutes.md", "minutes.spk.md", "minutes.prev.md",
    "minutes.evidence.json", "meeting.facts.json", "meeting.generation.json", "meeting.topic-map.json",
    ".topic-map-work.json", "transcript.review.json", "transcript.edits.json",
}


def _managed_meeting(path: Path) -> Path:
    data_root = Path(os.environ.get(
        "MEETING_DATA_ROOT", os.environ.get("MEETING_MINUTES_ROOT", ROOT))).resolve()
    resolved = path.resolve()
    if resolved.parent != (data_root / "meetings").resolve() or not resolved.is_dir():
        raise ValueError("会议目录不在受控 meetings 边界内")
    return resolved


def _version_files(mdir: Path) -> list[Path]:
    files = [path for path in mdir.iterdir()
             if path.is_file() and (path.name in CORE_FILES
                                    or ".translation." in path.name)]
    samples = mdir / "samples"
    if samples.is_dir():
        files.extend(path for path in samples.rglob("*") if path.is_file())
    return sorted(files)


def _snapshot(mdir: Path) -> tuple[Path, set[Path]]:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    version = mdir / ".versions" / f"before-local-asr-{stamp}"
    suffix = 1
    while version.exists():
        suffix += 1
        version = mdir / ".versions" / f"before-local-asr-{stamp}-{suffix}"
    version.mkdir(parents=True)
    existing: set[Path] = set()
    for source in _version_files(mdir):
        relative = source.relative_to(mdir)
        existing.add(relative)
        destination = version / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    (version / "manifest.json").write_text(json.dumps({
        "schema": "meeting-local-asr-backup/v1",
        "created_at": time.time(),
        "files": [str(path) for path in sorted(existing)],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return version, existing


def _restore(mdir: Path, version: Path, existing: set[Path]) -> None:
    # 先清掉本次新增的可预期派生文件，再恢复快照；母版与视觉资产不在清理集。
    current = _version_files(mdir)
    for path in current:
        relative = path.relative_to(mdir)
        if relative not in existing:
            path.unlink(missing_ok=True)
    samples = mdir / "samples"
    if samples.is_dir():
        shutil.rmtree(samples)
    for relative in existing:
        source = version / relative
        destination = mdir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="已有会议使用当前 ASR provider 重新转写")
    parser.add_argument("meeting_dir", type=Path)
    args = parser.parse_args()
    try:
        mdir = _managed_meeting(args.meeting_dir)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    videos = sorted(path for path in mdir.glob("source_video.*") if path.is_file())
    audios = sorted(path for path in mdir.glob("source_audio.*") if path.is_file())
    if not audios and not videos and (mdir / "audio.wav").is_file():
        audios = [mdir / "audio.wav"]
    if not videos and not audios:
        print("没有受保护的音视频母版，不能重转写", file=sys.stderr)
        return 2
    external = next((mdir / f"source.{suffix}" for suffix in ("docx", "vtt")
                     if (mdir / f"source.{suffix}").is_file()), None)
    def interrupted(_signum, _frame):
        raise InterruptedError("重转写被取消")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    progress_event("retranscribe_prepare")
    version, existing = _snapshot(mdir)
    print(f"[meta] 已创建重转写前快照，保留 {len(existing)} 个派生文件", flush=True)
    phase_done("retranscribe_prepare")
    if videos:
        command = [str(PY), str(ROOT / "bin" / "video_minutes.py"), str(videos[0]),
                   "--meeting-dir", str(mdir), "--reuse-visuals"]
        if external is not None:
            command += ["--ignored-transcript", str(external)]
    else:
        command = [str(PY), str(ROOT / "bin" / "run_all.py"), str(audios[0]),
                   "--meeting-dir", str(mdir), "--title", mdir.name]
    try:
        result = subprocess.run(command)
    except (InterruptedError, KeyboardInterrupt):
        _restore(mdir, version, existing)
        print("[meta] 本地 ASR 已取消，已恢复重转写前文本资产", flush=True)
        return 130
    if result.returncode:
        _restore(mdir, version, existing)
        print("[meta] 本地 ASR 失败，已恢复重转写前文本资产", flush=True)
        return result.returncode
    rag = mdir / ".rag"
    if rag.is_dir():
        shutil.rmtree(rag)
    print("[meta] 已使用当前 ASR provider 重建；原始母版和恢复快照均已保留", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
