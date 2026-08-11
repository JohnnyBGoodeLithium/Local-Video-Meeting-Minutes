"""会议目录命名规则（bin 下各脚本共用）。

目录结构：meetings/<日期>_<标题或录音时间>/，每场会议自包含：
audio.wav / transcript.* / diarization.json / minutes*.md / slides/ / samples/
"""

import os
import re
import shutil
import subprocess
from pathlib import Path


def _slug(text: str) -> str:
    text = re.sub(r"[^\w一-鿿-]+", "-", text).strip("-")
    return re.sub(r"-{2,}", "-", text) or "meeting"


def for_recording(root: Path, wav_stem: str, title: str = None) -> Path:
    """录音笔文件 20260806171137 → meetings/2026-08-06_171137（或 _<title>）。"""
    m = re.match(r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})", wav_stem)
    if m:
        y, mo, d, h, mi, s = m.groups()
        date, tag = f"{y}-{mo}-{d}", f"{h}{mi}{s}"
    else:
        date, tag = "undated", _slug(wav_stem)
    return Path(root) / "meetings" / f"{date}_{_slug(title) if title else tag}"


def for_teams(root: Path, slug_title: str, date_yyyymmdd: str) -> Path:
    if re.fullmatch(r"\d{8}", date_yyyymmdd or ""):
        d = f"{date_yyyymmdd[:4]}-{date_yyyymmdd[4:6]}-{date_yyyymmdd[6:8]}"
    else:
        d = "undated"
    return Path(root) / "meetings" / f"{d}_{_slug(slug_title)}"


def materialize_source(source: Path, destination: Path) -> Path:
    """把源媒体固化进会议目录：优先硬链接，跨文件系统时才复制。

    源文件之后即使从 inbox/下载目录删除，会议目录里的硬链接仍然有效。
    已存在的目标不静默覆盖，方便同一会议目录安全重跑。
    """
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.is_file():
            return destination
        raise IsADirectoryError(destination)
    incoming = destination.with_name(f".{destination.name}.incoming-{os.getpid()}")
    incoming.unlink(missing_ok=True)
    try:
        try:
            os.link(source, incoming)
        except OSError:
            shutil.copy2(source, incoming)
        incoming.replace(destination)
    finally:
        incoming.unlink(missing_ok=True)
    return destination


def materialize_audio(source: Path, destination: Path) -> Path:
    """固化为会议目录的 audio.wav；非 WAV 输入用 ffmpeg 转为 PCM 16k 单声道。"""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source.suffix.lower() in {".wav", ".wave"}:
        return materialize_source(source, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        return destination
    incoming = destination.with_name(f".{destination.name}.incoming-{os.getpid()}")
    incoming.unlink(missing_ok=True)
    try:
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", "-f", "wav", str(incoming)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode or not incoming.is_file():
            raise RuntimeError("ffmpeg 无法把输入音频固化为 audio.wav")
        incoming.replace(destination)
    finally:
        incoming.unlink(missing_ok=True)
    return destination
