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
from meeting_core.media_captions import (build_ytdlp_caption_fetcher,
                                         CaptionPreparation, prepare_captions)
from meeting_core.progress_events import phase_done, progress as progress_event
from meeting_dir import for_teams, materialize_source
from teams_minutes import slugify


ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
PY = Path(os.environ.get("MEETING_PYTHON", sys.executable)).expanduser()
DEFAULT_MAX_DURATION = 6 * 60 * 60
DEFAULT_MAX_FILESIZE = 8 * 1024 * 1024 * 1024
MEDIA_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi",
                    ".flv", ".mpeg", ".mpg", ".ts", ".m2ts", ".ogg"}


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


def _media_file(destination: Path) -> Path:
    candidates = sorted(destination.glob("download.*"), key=lambda p: p.stat().st_mtime,
                        reverse=True)
    # 字幕、封面和下载器 sidecar 永远不能被误当作视频母版。
    media = next((path for path in candidates if path.is_file()
                  and path.suffix.lower() in MEDIA_EXTENSIONS), None)
    if media is None:
        raise RuntimeError("download_missing")
    return media


def _media_duration(media: Path) -> float | None:
    """用下载后媒体校验字幕时间，避免平台预览时长与实际音轨不一致。"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(media)],
            capture_output=True, text=True, check=True, timeout=30)
        duration = float(result.stdout.strip())
        return duration if 0 < duration < float("inf") else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _download(url: str, destination: Path) -> tuple[Path, dict, CaptionPreparation]:
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
            progress_event("download", done=bucket, total=100, unit="percent")

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
        media = _media_file(destination)
        if media.stat().st_size > max_filesize:
            raise MediaURLRejected("file_too_large")
        duration = _media_duration(media)
        if duration and duration > max_duration:
            raise MediaURLRejected("duration_too_long")
        caption_info = dict(info if isinstance(info, dict) else preview)
        if duration:
            caption_info["duration"] = duration
        captions = prepare_captions(
            caption_info, destination / "captions", build_ytdlp_caption_fetcher(
                downloader, validate_url=validate_public_url))
    return media, info if isinstance(info, dict) else preview, captions


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _new_import_directory(base: Path) -> Path:
    """每次链接导入创建独立资料，原子避免覆盖旧字幕、人工修正与并发导入。"""
    for number in range(1, 1001):
        destination = base if number == 1 else base.with_name(f"{base.name}-import-{number}")
        try:
            destination.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        if number > 1:
            print("[meta] 已有资料保持不变，本次创建独立导入副本", flush=True)
        return destination
    raise MediaURLRejected("too_many_import_copies")


def main() -> int:
    parser = argparse.ArgumentParser(description="公开媒体链接 → 本地 media 分析")
    parser.add_argument("request", type=Path, help="私有请求 JSON（含 url）")
    parser.add_argument("--result", type=Path, required=True, help="仅含 meeting slug 的结果 JSON")
    parser.add_argument("--no-vl", action="store_true")
    parser.add_argument("--visual-mode", choices=["slides", "media"], default=None)
    args = parser.parse_args()

    try:
        progress_event("download", done=0, total=100, unit="percent")
        request = json.loads(args.request.read_text(encoding="utf-8"))
        url = validate_public_url(str(request.get("url") or ""))
        media, info, captions = _download(url, args.request.parent)
        phase_done("download", done=100, total=100, unit="percent")
        source_info = from_ytdlp(info)
        source_info["captions"] = captions.provenance
        title = str(source_info.get("title") or "Internet media").strip()[:180] or "Internet media"
        upload_date = str(info.get("upload_date") or "")
        unique = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
        data_root = Path(os.environ.get(
            "MEETING_DATA_ROOT", os.environ.get("MEETING_MINUTES_ROOT", ROOT))).resolve()
        mdir = _new_import_directory(for_teams(
            data_root, f"{slugify(title)}-{unique}", upload_date))
        _atomic_json(args.result, {"meeting": mdir.name})

        # 标题、来源与内容类型必须在生成语音草稿前可用：媒体 prompt、处理中列表和
        # 失败恢复都依赖它们。video_minutes 会在写 source.json 时保留未知字段。
        _atomic_json(mdir / "meta.json", {
            "title": title,
            "title_origin": "source",
            "content_type": "media",
        })
        _atomic_json(mdir / "source.json", {"source_info": source_info})

        # 保存下载过的原始字幕（含被拒绝的尝试），不保存下载 URL、cookie 或请求头。
        for raw in sorted((args.request.parent / "captions").glob("*.vtt")):
            materialize_source(raw, mdir / "source_captions" / raw.name)

        command = [str(PY), str(BIN / "video_minutes.py"), str(media),
                   "--meeting-dir", str(mdir), "--slug", title, "--media"]
        if captions.usable:
            raw = materialize_source(captions.raw_path, mdir / "source.vtt")
            command += ["--subtitle", str(raw), "--subtitle-language",
                        captions.provenance["language"], "--subtitle-kind",
                        captions.provenance["kind"]]
        if args.no_vl:
            command.append("--no-vl")
        if args.visual_mode:
            command += ["--visual-mode", args.visual_mode]
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
