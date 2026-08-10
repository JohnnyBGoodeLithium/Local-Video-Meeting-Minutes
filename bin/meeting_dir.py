"""会议目录命名规则（bin 下各脚本共用）。

目录结构：meetings/<日期>_<标题或录音时间>/，每场会议自包含：
audio.wav / transcript.* / diarization.json / minutes*.md / slides/ / samples/
"""

import re
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
