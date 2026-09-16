#!/usr/bin/env python3
"""虚构共享屏幕：分类与抽取独立，参与者栏变动不增加逻辑页。"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))
import slide_pages
from meeting_core.visual_mode import configure_extraction

with tempfile.TemporaryDirectory(prefix="visual-mode-") as tmp:
    mdir = Path(tmp)
    meta_path = mdir / "meta.json"
    meta_path.write_text('{"title":"Synthetic talk","content_type":"media"}')
    assert configure_extraction(mdir, "slides", media=True) == "slides"
    meta = json.loads(meta_path.read_text())
    assert meta["content_type"] == "media" and meta["title"] == "Synthetic talk"
    assert configure_extraction(mdir) == "slides"  # 恢复不会退回默认媒体镜头
    assert configure_extraction(mdir, "media") == "media"
    original = meta_path.read_bytes()
    try:
        configure_extraction(mdir, "invalid")
        raise AssertionError("invalid mode accepted")
    except ValueError:
        pass
    assert meta_path.read_bytes() == original

    # 两页课件，右侧参与者栏每十秒变一次，共12种布局。
    rng = np.random.default_rng(41)
    frames = np.full((120, 180, 320), 225, dtype=np.uint8)
    frames[:, 30:33, 20:250] = 30
    frames[:60, 65:135, 30:120] = 50
    frames[60:, 65:135, 140:230] = 50
    for start in range(0, 120, 10):
        frames[start:start+10, :, 272:] = rng.integers(0, 255, (180, 48), dtype=np.uint8)
    def decode(*args, **kwargs):
        if kwargs.get("talk_stats"):
            return frames, {"skin": np.zeros(120), "edge": np.ones(120)}
        return frames
    def grab(_video, _time, _width, out):
        out.write_bytes(b"synthetic screenshot")
    mode = configure_extraction(mdir, "slides")
    with patch.object(slide_pages, "_decode_small", side_effect=decode), \
            patch.object(slide_pages, "_grab_frame", side_effect=grab):
        pages = slide_pages.extract_pages(mdir / "fake.mp4", mdir / "slides", mode=mode, verbose=False)
        shots = slide_pages.extract_pages(mdir / "fake.mp4", mdir / "shots", mode="media", verbose=False)
    assert len(pages) == 2, len(pages)
    assert pages[0]["ranges"] == [[0.0, 60.0]] and pages[1]["ranges"] == [[60.0, 120.0]]
    assert len(shots) > len(pages), (len(shots), len(pages))
    assert json.loads(meta_path.read_text())["content_type"] == "media"
    print(f"Visual extraction: {len(shots)} video shots -> {len(pages)} shared-screen pages; media semantics and recovery retained")
