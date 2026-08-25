#!/usr/bin/env python3
"""content_type 读取口径与白名单：缺省/未知值一律按 meeting（全虚构）。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
sys.path.insert(0, str(PROJECT / "web"))
import deps  # noqa: E402


# 白名单只认 meeting / media；缺省、未知、非字符串都回退 meeting，存量零迁移。
assert deps.CONTENT_TYPES == ("meeting", "media")
assert deps._content_type("meeting") == "meeting"
assert deps._content_type("media") == "media"
assert deps._content_type(None) == "meeting"
assert deps._content_type("") == "meeting"
assert deps._content_type("podcast") == "meeting"
assert deps._content_type("Media") == "meeting"  # 大小写敏感，未知即回退

with tempfile.TemporaryDirectory(prefix="content-type-test-") as tmp:
    meetings = Path(tmp) / "meetings"
    deps.MEETINGS = meetings  # deps 模块级常量，测试内指向临时目录

    bare = meetings / "2026-08-01_alpha"
    bare.mkdir(parents=True)
    ident = deps._meeting_identity("2026-08-01_alpha")
    assert ident["content_type"] == "meeting" and ident["title"] == "alpha"

    media = meetings / "2026-08-02_beta"
    media.mkdir(parents=True)
    (media / "meta.json").write_text(json.dumps(
        {"title": "虚构媒体", "content_type": "media"}, ensure_ascii=False),
        encoding="utf-8")
    ident = deps._meeting_identity("2026-08-02_beta")
    assert ident["content_type"] == "media" and ident["title"] == "虚构媒体"

    unknown = meetings / "2026-08-03_gamma"
    unknown.mkdir(parents=True)
    (unknown / "meta.json").write_text(json.dumps(
        {"content_type": "vlog"}, ensure_ascii=False), encoding="utf-8")
    assert deps._meeting_identity("2026-08-03_gamma")["content_type"] == "meeting"

print("content_type_test: OK")
