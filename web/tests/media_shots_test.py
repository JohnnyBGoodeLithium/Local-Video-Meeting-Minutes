#!/usr/bin/env python3
"""media 镜头检测模式：全合成视频 + 纯数组单测，不碰真实会议文件。"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
from slide_pages import _shot_cuts, _shot_thresholds, extract_pages  # noqa: E402

assert shutil.which("ffmpeg"), "media 镜头测试需要 ffmpeg"

# ---- 纯数组：自适应阈值与局部峰切点 ----------------------------------------
dist = np.array([2.0, 2.5, 2.0, 2.0, 2.0, 30.0, 3.0, 2.0,
                 2.0, 2.0, 2.0, 2.0, 25.0, 25.0, 2.0, 2.0])
th, th_same = _shot_thresholds(dist)
assert th == 12.0 and th_same == 4.0            # max(8, p50×6) / max(4, p50×2)
assert _shot_thresholds(np.full(10, 0.5)) == (8.0, 4.0)   # 绝对下限
# 局部峰：索引 5 是切点；12/13 平台只取一次；基线内 2.5 不触发
assert _shot_cuts(dist, th) == [6, 14]
assert _shot_cuts(np.array([2.0, 7.0, 2.0]), 8.0) == []    # 低于阈值的孤立峰不切
assert _shot_cuts(np.array([2.0, 30.0, 2.0]), 8.0) == [2]  # 显著峰 → 切点


# ---- 合成视频 --------------------------------------------------------------
def make_video(path: Path, shots: list[tuple[str, float]]):
    inputs = []
    for src, dur in shots:
        inputs += ["-f", "lavfi", "-t", f"{dur}", "-i", src]
    labels = "".join(f"[{i}:v]" for i in range(len(shots)))
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *inputs,
         "-filter_complex", f"{labels}concat=n={len(shots)}:v=1:a=0[v]",
         "-map", "[v]", "-pix_fmt", "yuv420p", str(path)],
        check=True)


with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    # 6 段硬切：A(testsrc 静态图案) → 蓝 → 白(1s 过短) → mandelbrot → A 重演 → 绿
    media_mp4 = tmp / "media.mp4"
    make_video(media_mp4, [
        ("testsrc=size=320x180:rate=10", 6),
        ("color=c=blue:size=320x180:rate=10", 4),
        ("color=c=white:size=320x180:rate=10", 1),
        ("mandelbrot=size=320x180:rate=10", 6),
        ("testsrc=size=320x180:rate=10", 6),
        ("color=c=green:size=320x180:rate=10", 4),
    ])

    # ---- media 模式端到端 --------------------------------------------------
    pages = extract_pages(media_mp4, tmp / "shots", tmp / "shots.json",
                          mode="media", verbose=False)
    assert len(pages) == 4, f"应去重为 4 个镜头页, 实际 {len(pages)}"
    assert sum(len(p["ranges"]) for p in pages) == 5       # 1s 短镜头被并回邻居
    repeated = [p for p in pages if len(p["ranges"]) == 2]
    assert len(repeated) == 1, "重复出现的镜头应被签名合并为一页"
    rep = repeated[0]
    assert rep["ranges"][0][0] == 0.0 and rep["ranges"][1][0] >= 16.0
    for p in pages:                                        # 结构兼容 + 代表帧
        assert p["image"].is_file()
        s, e = p["ranges"][0]
        assert s - 1.0 <= p["captured"] <= e + 1.0
        assert e - s >= 1.5, "过短镜头应并回邻居, 不单独成页"
    timeline = json.loads((tmp / "shots.json").read_text(encoding="utf-8"))
    assert len(timeline) == 4
    for entry in timeline:
        assert entry["kind"] == "slide"                    # 下游按 kind==slide 消费
        assert entry["shot"] is True
        assert {"kind", "page", "first", "image", "captured", "ranges"} <= set(entry)
        assert Path(tmp / "shots", entry["image"]).is_file()
    assert [e["first"] for e in timeline] == sorted(e["first"] for e in timeline)

    # ---- 上限保护：max_pages=2 保留时长最长的两页并标注 truncated ----------
    pages_cap = extract_pages(media_mp4, tmp / "shots_cap", tmp / "shots_cap.json",
                              mode="media", max_pages=2, verbose=False)
    assert len(pages_cap) == 2
    assert [p["page"] for p in pages_cap] == [1, 2]        # 截断后页码重排
    assert pages_cap[0]["first"] == 0.0                    # 重演合并页总时长最长
    for p in pages_cap:
        assert p["image"].is_file()
        assert p["image"].name.startswith(f"page_{p['page']:02d}_")  # 截断重排后名实一致
    cap_tl = json.loads((tmp / "shots_cap.json").read_text(encoding="utf-8"))
    assert all(e.get("truncated") is True for e in cap_tl)
    assert len(list((tmp / "shots_cap").glob("page_*.jpg"))) == 2  # 被截镜头不留孤儿截图

    # ---- 回归：默认 slides 模式行为不变 ------------------------------------
    slides_mp4 = tmp / "slides.mp4"
    make_video(slides_mp4, [
        ("color=c=yellow:size=320x180:rate=10", 4),
        ("color=c=red:size=320x180:rate=10", 4),
    ])
    spages = extract_pages(slides_mp4, tmp / "slides", tmp / "slides.json",
                           threshold=2.0, verbose=False)
    assert len(spages) == 2, f"静态翻页应切 2 页, 实际 {len(spages)}"
    stl = json.loads((tmp / "slides.json").read_text(encoding="utf-8"))
    assert all(e["kind"] == "slide" and "shot" not in e and "truncated" not in e
               for e in stl)

print("Media shots: 镜头切分/签名合并/截断/结构兼容通过; slides 模式回归不变")
