#!/usr/bin/env python3
"""VL 空正文不能成为成功缓存，旧空项必须补算。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
import minutes_by_page as mb  # noqa: E402


class FakeModelsResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"data": [{"id": "synthetic-vl"}]}).encode("utf-8")


with tempfile.TemporaryDirectory(prefix="vl-cache-test-") as temp:
    mdir = Path(temp)
    (mdir / "slides").mkdir()
    for name in ("one.jpg", "two.jpg", "three.jpg"):
        (mdir / "slides" / name).write_bytes(b"synthetic")
    (mdir / "page_desc.json").write_text(json.dumps({
        "model": "old-vl",
        "desc": {
            "1": "<think>旧的未闭合推理，没有正文",
            "2": "## 标题\n已完成页面\n## 信息价值\nhigh：合成数据表。",
        },
    }, ensure_ascii=False), encoding="utf-8")
    pages = [
        {"page": 1, "image": "one.jpg", "first": 0},
        {"page": 2, "image": "two.jpg", "first": 10},
        {"page": 3, "image": "three.jpg", "first": 20},
    ]
    calls = {1: 0, 2: 0, 3: 0}

    def fake_chat(_api, _model, image, _max_tokens, _prompt):
        page = {"one.jpg": 1, "two.jpg": 2, "three.jpg": 3}[image.name]
        calls[page] += 1
        if page == 1 and calls[page] == 2:
            return (json.dumps({"type": "表格页", "title": "补算成功",
                                "summary": "合成表格包含关键指标。"}, ensure_ascii=False),
                    {"completion_tokens": 40})
        return "<think>只有推理，没有正文", {"completion_tokens": 20}

    original_urlopen = mb.urllib.request.urlopen
    original_chat = mb.chat_with_image
    try:
        mb.urllib.request.urlopen = lambda *_args, **_kwargs: FakeModelsResponse()
        mb.chat_with_image = fake_chat
        descriptions = mb.describe_pages(mdir, pages, "http://synthetic/v1")
    finally:
        mb.urllib.request.urlopen = original_urlopen
        mb.chat_with_image = original_chat

    assert calls == {1: 2, 2: 0, 3: 2}
    assert set(descriptions) == {1, 2}
    persisted = json.loads((mdir / "page_desc.json").read_text(encoding="utf-8"))["desc"]
    assert set(persisted) == {"1", "2"}
    assert persisted["1"].startswith("## 标题")
    assert "页面类型：表格页" in persisted["1"]
    assert persisted["2"].startswith("## 标题")

print("VL cache: empty output retried and never persisted as success")
