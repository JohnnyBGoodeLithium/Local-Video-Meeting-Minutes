#!/usr/bin/env python3
"""公开视频来源契约：只测试纯函数，不访问网络、不下载真实内容。"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from media_url import MediaURLRejected, normalize_url_shape  # noqa: E402
from meeting_core.source_info import (from_ytdlp, load_source_info,  # noqa: E402
                                      project_source_info)


assert normalize_url_shape(" HTTPS://Example.invalid/watch?v=fake#fragment ") == \
    "https://Example.invalid/watch?v=fake"
for bad in ("file:///etc/passwd", "http://localhost/video", "http://user:pass@example.invalid/x"):
    try:
        normalize_url_shape(bad)
    except MediaURLRejected:
        pass
    else:
        raise AssertionError(f"危险 URL 未被拒绝: {bad}")

source = from_ytdlp({
    "extractor_key": "Youtube",
    "id": "synthetic-video",
    "webpage_url": "https://www.youtube.com/watch?v=synthetic",
    "title": " Synthetic Product Keynote ",
    "channel": "Example Publisher",
    "channel_id": "example-channel",
    "upload_date": "20260820",
    "duration": 125.456,
    "http_headers": {"Authorization": "must-not-leak"},
    "cookies": "must-not-leak",
    "requested_downloads": [{"filepath": "/private/path"}],
})
assert source == {
    "schema": "media-source/v1",
    "kind": "public_url",
    "canonical_url": "https://www.youtube.com/watch?v=synthetic",
    "platform": "YouTube",
    "platform_id": "synthetic-video",
    "title": "Synthetic Product Keynote",
    "publisher": "Example Publisher",
    "publisher_id": "example-channel",
    "published_at": "2026-08-20",
    "duration": 125.456,
}
serialized = json.dumps(source)
assert "Authorization" not in serialized and "private/path" not in serialized

with tempfile.TemporaryDirectory(prefix="media-source-test-") as temp:
    mdir = Path(temp)
    (mdir / "source.json").write_text(json.dumps({"source_info": source}), encoding="utf-8")
    assert load_source_info(mdir) == source

assert project_source_info({"source_info": {**source, "cookies": "secret"}}) == source
assert project_source_info({"source_url": "https://example.invalid/public"})["canonical_url"] \
    == "https://example.invalid/public"
assert project_source_info({"source_url": "http://user:secret@example.invalid/x"}) == {}

generic = from_ytdlp({
    "extractor": "generic",
    "webpage_url": "https://cdn.example.invalid/video.mp4?token=secret",
    "title": "Direct video",
})
assert "canonical_url" not in generic
assert generic["title"] == "Direct video"
assert project_source_info(generic)["title"] == "Direct video"

print("media url/source info tests passed")
