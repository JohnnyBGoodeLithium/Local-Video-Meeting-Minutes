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
from slide_pages import (_TALK_DHASH_HAM, _dhash16, _edge_density, _hamming,  # noqa: E402
                         _shot_cuts, _shot_thresholds, _skin_fraction, extract_pages)

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


# ---- 纯数组：口播代理（肤色/边缘密度）与 dHash ------------------------------
def _gray_of(frame: np.ndarray) -> np.ndarray:
    v = frame.astype(np.uint16)
    return ((77 * v[..., 0] + 150 * v[..., 1] + 29 * v[..., 2] + 128) >> 8).astype(np.uint8)


def _talk_frame(offset=0, tone=(220, 170, 140)) -> np.ndarray:
    """合成口播特写：平滑背景 + 中央肤色块（主讲人），offset/tone 模拟姿势微变。"""
    h, w = 180, 320
    yy = np.linspace(40, 120, h, dtype=np.float32)[:, None]
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[..., 0] = (55 + yy * 0.2).astype(np.uint8)
    frame[..., 1] = (65 + yy * 0.5).astype(np.uint8)
    frame[..., 2] = (100 + yy * 0.4).astype(np.uint8)
    bh, bw = 90, 110
    r0, c0 = (h - bh) // 2, (w - bw) // 2 + offset
    frame[r0:r0 + bh, c0:c0 + bw] = tone
    return frame


def _chart_frame(heights) -> np.ndarray:
    """同版式图表：固定坐标轴与柱位，heights 不同即"不同数据"。"""
    frame = np.full((180, 320, 3), 235, dtype=np.uint8)
    frame[20:160, 30:33] = 20
    frame[157:160, 30:300] = 20
    for r in (45, 75, 105):                      # 伪文字行抬高文字/边缘密度
        frame[r:r + 3, 40:280:6] = 30
    for i, hgt in enumerate(heights):
        c0 = 50 + i * 40
        frame[160 - hgt:158, c0:c0 + 24] = (40, 90, 160)
    return frame


_talk_a = _talk_frame(0, (230, 180, 150))
_talk_b = _talk_frame(4, (175, 125, 95))
_chart_x = _chart_frame([60, 100, 80, 120, 90, 70])
_chart_y = _chart_frame([60, 55, 80, 75, 90, 70])
_ga, _gb = _gray_of(_talk_a), _gray_of(_talk_b)
# 口播候选闸门：中央肤色占比高 + 全帧边缘密度低
assert _skin_fraction(_talk_a) >= 0.5 and _edge_density(_ga) < 0.02
# 姿势微变：全帧均差远超同镜头阈值 4.0（严格通道合并不了），dHash 却近重复
assert np.abs(_ga.astype(np.float32) - _gb.astype(np.float32)).mean() > 4.0
assert _hamming(_dhash16(_ga), _dhash16(_gb)) <= _TALK_DHASH_HAM
assert _hamming(_dhash16(_ga), _dhash16(_ga)) == 0
# 图表帧：肤色≈0 → 永不进口播 dHash 通道；同版式不同数据全帧差 > 4 也不误并
assert _skin_fraction(_chart_x) < 0.01 and _skin_fraction(_chart_y) < 0.01
_gx, _gy = _gray_of(_chart_x), _gray_of(_chart_y)
assert np.abs(_gx.astype(np.float32) - _gy.astype(np.float32)).mean() > 4.0
# 关键：同版式图表的 dHash 也很近（版式同构）——防误并完全依赖候选闸门
assert _hamming(_dhash16(_gx), _dhash16(_gy)) <= _TALK_DHASH_HAM


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

    # ---- 口播二次合并：肤色块+微位移的重复口播镜头 → 一页 talking_head ------
    def make_frames_video(path: Path, clips: list[tuple[np.ndarray, float]]):
        proc = subprocess.Popen(
            ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", "320x180", "-r", "10", "-i", "-", "-pix_fmt", "yuv420p", str(path)],
            stdin=subprocess.PIPE)
        for frame, dur in clips:
            blob = np.ascontiguousarray(frame.astype(np.uint8)).tobytes()
            for _ in range(int(round(dur * 10))):
                proc.stdin.write(blob)
        proc.stdin.close()
        assert proc.wait() == 0

    talk_mp4 = tmp / "talk.mp4"
    make_frames_video(talk_mp4, [
        (_talk_frame(0, (230, 180, 150)), 3),      # 口播 A
        (_chart_x, 3),                             # 图表 X
        (_talk_frame(4, (175, 125, 95)), 3),       # 口播 B：微位移+明暗变化
        (_chart_y, 3),                             # 图表 Y：同版式不同数据
        (_talk_frame(-4, (205, 155, 125)), 3),     # 口播 C
    ])
    tpages = extract_pages(talk_mp4, tmp / "talk_shots", tmp / "talk.json",
                           mode="media", verbose=False)
    heads = [p for p in tpages if p["talking_head"]]
    assert len(heads) == 1, f"三段口播应合并为一页, 实际 {len(heads)}: {tpages}"
    head = heads[0]
    assert len(head["ranges"]) == 3, "口播页 ranges 应累记三次出现区间"
    starts = sorted(r[0] for r in head["ranges"])
    assert all(abs(a - b) <= 1.5 for a, b in zip(starts, [0.0, 6.0, 12.0]))
    charts = [p for p in tpages if not p["talking_head"]]
    assert len(charts) == 2, "同版式不同数据的图表帧绝不走 dHash 通道合并"
    assert all(len(p["ranges"]) == 1 for p in charts)
    ttl = json.loads((tmp / "talk.json").read_text(encoding="utf-8"))
    tl_heads = [e for e in ttl if e.get("talking_head") is True]
    assert len(tl_heads) == 1 and len(tl_heads[0]["ranges"]) == 3
    assert sum(1 for e in ttl if "talking_head" not in e) == 2  # 图表页不带标记

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

print("Media shots: 镜头切分/签名合并/口播dHash二次合并/图表防误并/截断/结构兼容通过; slides 模式回归不变")
