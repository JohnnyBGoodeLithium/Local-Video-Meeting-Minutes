#!/usr/bin/env python3
"""下载一个公开互联网视频并进入 media 处理管线。

URL 只从私有 inbox 请求文件读取，不打印到 stdout/stderr，也不写入作业 JSON。
下载完成后把原始链接保存在该媒体自己的 meta/source sidecar 中，供来源追溯；
子进程 stdout 仍只输出 ``[meta]`` 进度，不输出标题、URL 或下载器正文。
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from meeting_core.source_info import from_ytdlp
from meeting_dir import for_teams
from teams_minutes import slugify


ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
PY = Path(os.environ.get("MEETING_PYTHON", sys.executable)).expanduser()
DEFAULT_MAX_DURATION = 6 * 60 * 60
DEFAULT_MAX_FILESIZE = 8 * 1024 * 1024 * 1024


class MediaURLRejected(ValueError):
    """URL 不满足公开网络媒体入口的安全边界。"""


def normalize_url_shape(raw: str) -> str:
    """只做无网络的 URL 形态校验；DNS/IP 校验在下载进程内完成。"""
    value = str(raw or "").strip()
    if not value or len(value) > 4096:
        raise MediaURLRejected("invalid_length")
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise MediaURLRejected("unsupported_scheme")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise MediaURLRejected("invalid_authority")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal")):
        raise MediaURLRejected("local_host")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/",
                       parsed.query, ""))


def _public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(address.is_global)


def validate_public_url(raw: str) -> str:
    """拒绝解析到本机、局域网、链路本地或保留地址的初始 URL。"""
    value = normalize_url_shape(raw)
    host = urlsplit(value).hostname or ""
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except OSError as exc:
        raise MediaURLRejected("dns_failed") from exc
    if not addresses or any(not _public_address(address) for address in addresses):
        raise MediaURLRejected("non_public_address")
    return value


class _SafeLogger:
    """yt-dlp 日志可能带 URL、标题或 Cookie；这里全部丢弃。"""

    def debug(self, _message):
        return None

    def info(self, _message):
        return None

    def warning(self, _message):
        return None

    def error(self, _message):
        return None


def _download(url: str, destination: Path) -> tuple[Path, dict]:
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("downloader_unavailable") from exc

    max_height = max(360, int(os.environ.get("MEETING_MEDIA_MAX_HEIGHT", "1080")))
    max_duration = max(60, int(os.environ.get(
        "MEETING_MEDIA_MAX_DURATION", str(DEFAULT_MAX_DURATION))))
    max_filesize = max(100 * 1024 * 1024, int(os.environ.get(
        "MEETING_MEDIA_MAX_FILESIZE", str(DEFAULT_MAX_FILESIZE))))
    destination.mkdir(parents=True, exist_ok=True)
    last_percent = {"value": -10}

    def progress(event: dict) -> None:
        if event.get("status") != "downloading":
            return
        downloaded = int(event.get("downloaded_bytes") or 0)
        total = int(event.get("total_bytes") or event.get("total_bytes_estimate") or 0)
        if total <= 0:
            return
        percent = int(downloaded * 100 / total)
        bucket = max(0, min(100, percent // 10 * 10))
        if bucket >= last_percent["value"] + 10:
            last_percent["value"] = bucket
            print(f"[meta] 下载媒体 {bucket}%", flush=True)

    options = {
        "format": f"bv*[height<={max_height}]+ba/b[height<={max_height}]/best",
        "merge_output_format": "mp4",
        "outtmpl": str(destination / "download.%(ext)s"),
        "noplaylist": True,
        "playlistend": 1,
        "quiet": True,
        "no_warnings": True,
        "logger": _SafeLogger(),
        "progress_hooks": [progress],
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "max_filesize": max_filesize,
        "overwrites": False,
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        preview = downloader.extract_info(url, download=False)
        if not isinstance(preview, dict) or preview.get("_type") in {"playlist", "multi_video"}:
            raise MediaURLRejected("playlist_not_supported")
        if preview.get("is_live"):
            raise MediaURLRejected("live_not_supported")
        duration = float(preview.get("duration") or 0)
        if duration and duration > max_duration:
            raise MediaURLRejected("duration_too_long")
        print("[meta] 链接已解析，开始下载公开视频", flush=True)
        info = downloader.extract_info(url, download=True)

    candidates = sorted(destination.glob("download.*"), key=lambda p: p.stat().st_mtime,
                        reverse=True)
    media = next((path for path in candidates if path.is_file()
                  and path.suffix.lower() not in {".json", ".part", ".ytdl"}), None)
    if media is None:
        raise RuntimeError("download_missing")
    if media.stat().st_size > max_filesize:
        raise MediaURLRejected("file_too_large")
    return media, info if isinstance(info, dict) else preview


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="公开媒体链接 → 本地 media 分析")
    parser.add_argument("request", type=Path, help="私有请求 JSON（含 url）")
    parser.add_argument("--result", type=Path, required=True, help="仅含 meeting slug 的结果 JSON")
    parser.add_argument("--no-vl", action="store_true")
    args = parser.parse_args()

    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        url = validate_public_url(str(request.get("url") or ""))
        media, info = _download(url, args.request.parent)
        source_info = from_ytdlp(info)
        title = str(source_info.get("title") or "Internet media").strip()[:180] or "Internet media"
        upload_date = str(info.get("upload_date") or "")
        unique = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
        data_root = Path(os.environ.get(
            "MEETING_DATA_ROOT", os.environ.get("MEETING_MINUTES_ROOT", ROOT))).resolve()
        mdir = for_teams(data_root, f"{slugify(title)}-{unique}", upload_date)
        mdir.mkdir(parents=True, exist_ok=True)
        _atomic_json(args.result, {"meeting": mdir.name})

        # 标题、来源与内容类型必须在生成语音草稿前可用：媒体 prompt、处理中列表和
        # 失败恢复都依赖它们。video_minutes 会在写 source.json 时保留未知字段。
        _atomic_json(mdir / "meta.json", {
            "title": title,
            "title_origin": "source",
            "content_type": "media",
        })
        _atomic_json(mdir / "source.json", {"source_info": source_info})

        command = [str(PY), str(BIN / "video_minutes.py"), str(media),
                   "--meeting-dir", str(mdir), "--slug", title, "--media"]
        if args.no_vl:
            command.append("--no-vl")
        result = subprocess.run(command)
        if result.returncode:
            return result.returncode

        print("[meta] 公开视频已固化并完成媒体分析", flush=True)
        return 0
    except MediaURLRejected as exc:
        print(f"[error] 媒体链接被拒绝 ({exc})", flush=True)
        return 2
    except Exception as exc:
        print(f"[error] 媒体链接处理失败 ({type(exc).__name__})", flush=True)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
