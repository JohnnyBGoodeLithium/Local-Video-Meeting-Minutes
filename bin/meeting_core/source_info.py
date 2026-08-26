"""公开媒体来源的最小、可分享元数据契约。

下载器返回值可能包含 cookie、请求头、本机文件名和大量平台私有字段。业务层只保存
这里明确列出的字段；在线 bundle、MeetingPack 与 KB 导出再经 ``project_source_info``
投影，避免把原始 yt-dlp 字典传到浏览器或分享包。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


SCHEMA = "media-source/v1"
MAX_TEXT = 240


def _text(value, limit: int = MAX_TEXT) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _http_url(value) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 4096:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username is not None or parsed.password is not None:
        return ""
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/",
                       parsed.query, ""))


def _shareable_url(info: dict) -> str:
    """返回适合进入分享包的页面链接，而不是可能含签名参数的下载地址。"""
    url = _http_url(info.get("webpage_url") or info.get("original_url"))
    if not url:
        return ""
    extractor = re.sub(
        r"[^a-z0-9]+", "", _text(info.get("extractor_key") or info.get("extractor")).lower()
    )
    parsed = urlsplit(url)
    # 已知站点的 webpage_url 通常是稳定公开页面；generic 直链的 query 则常含
    # 临时签名、访问令牌或 CDN 鉴权信息，不能投影到 Viewer/KB。
    if extractor in {"generic", ""} and parsed.query:
        return ""
    return url


def _platform(info: dict) -> str:
    raw = _text(info.get("extractor_key") or info.get("extractor") or "")
    key = re.sub(r"[^a-z0-9]+", "", raw.lower())
    known = {
        "youtube": "YouTube",
        "youtubeweb": "YouTube",
        "bilibili": "Bilibili",
        "vimeo": "Vimeo",
        "ted": "TED",
        "linkedinlearning": "LinkedIn Learning",
        "x": "X",
        "twitter": "X",
    }
    if key in known:
        return known[key]
    return raw[:80] or "Web"


def _published_at(info: dict) -> str:
    for key in ("release_timestamp", "timestamp"):
        try:
            value = float(info.get(key) or 0)
            if value > 0:
                return datetime.fromtimestamp(value, timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            pass
    digits = re.sub(r"\D", "", str(info.get("release_date") or info.get("upload_date") or ""))
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def from_ytdlp(info: dict) -> dict:
    """把 yt-dlp 结果缩减为稳定的 ``media-source/v1``。"""
    if not isinstance(info, dict):
        info = {}
    canonical_url = _shareable_url(info)
    duration = 0.0
    try:
        duration = max(0.0, float(info.get("duration") or 0))
    except (TypeError, ValueError):
        pass
    payload = {
        "schema": SCHEMA,
        "kind": "public_url",
        "canonical_url": canonical_url,
        "platform": _platform(info),
        "platform_id": _text(info.get("id"), 120),
        "title": _text(info.get("title"), 180),
        "publisher": _text(info.get("channel") or info.get("uploader"), 160),
        "publisher_id": _text(info.get("channel_id") or info.get("uploader_id"), 160),
        "published_at": _published_at(info),
        "duration": round(duration, 3) if duration else 0,
    }
    return {key: value for key, value in payload.items() if value not in ("", 0, None)}


def project_source_info(value) -> dict:
    """白名单投影；兼容存量 ``source_url``，拒绝未知 schema/字段。"""
    if not isinstance(value, dict):
        return {}
    nested = value.get("source_info") if isinstance(value.get("source_info"), dict) else value
    url = _http_url(nested.get("canonical_url") or nested.get("source_url"))
    if not url and not any(_text(nested.get(key)) for key in (
        "platform", "title", "publisher", "published_at"
    )):
        return {}
    projected = {
        "schema": SCHEMA,
        "kind": "public_url",
        "canonical_url": url,
        "platform": _text(nested.get("platform"), 80),
        "platform_id": _text(nested.get("platform_id"), 120),
        "title": _text(nested.get("title"), 180),
        "publisher": _text(nested.get("publisher"), 160),
        "publisher_id": _text(nested.get("publisher_id"), 160),
        "published_at": _text(nested.get("published_at"), 20),
    }
    try:
        duration = max(0.0, float(nested.get("duration") or 0))
    except (TypeError, ValueError):
        duration = 0
    if duration:
        projected["duration"] = round(duration, 3)
    return {key: value for key, value in projected.items() if value not in ("", None)}


def load_source_info(mdir: Path) -> dict:
    """从会议目录读取公开来源；不抛出损坏 sidecar。"""
    for name in ("source.json", "meta.json"):
        try:
            raw = json.loads((Path(mdir) / name).read_text(encoding="utf-8"))
        except Exception:
            continue
        projected = project_source_info(raw)
        if projected:
            return projected
    return {}
