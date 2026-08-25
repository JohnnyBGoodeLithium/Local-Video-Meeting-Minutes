#!/usr/bin/env python3
"""屏幕共享录屏 → 逻辑页(deck page)抽取。

思路（替代旧的 ffmpeg scene-detect 瞬间帧方案）：
    1. 视频按低 fps(默认 1)重采样成小帧序列；稀疏高饱和激光点/红框
       先从用于判页的灰度帧中消除（不修改导出截图）
    2. 内容 ROI + 运动屏蔽：右侧参会人栏默认不参与页面判断；其余区域再统计
       逐像素时间平均变化，持续运动的摄像头/光标区也不参与差异计算
    3. 相邻帧算页面距离：全页稳定内容 + 顶部标题区增强。因此表格
       主体相似但大标题改变仍会切页，局部讲解标注不会。
       (距离分布是 静态≪小变化/build≪大翻页 三层，Otsu 二分会把线划进小变化层，
       漏掉 build；空档很宽所以自适应下限稳)，可 --threshold 手动覆盖
    4. 连续相似帧聚成稳定段；<min-seg 秒的段并回邻居(动画过渡被吃掉)
    5. 段签名 = 段内帧的逐像素中位数(抗激光笔/光标抖动)；
       新段与所有历史页签名比对(同页阈值≈翻页阈值/2 且 ≥1.0, 可 --same-threshold 覆盖)
       → 回翻旧页认得出，输出"页码 ↔ 时间段列表"时间线
    6. 每页截"与段签名最接近的一帧"(medoid)：动画已播完，且免疫并入段尾的
       1-2 秒杂质帧(共享闪断/黑帧——段末截图会被它们污染)
    7. 段内帧间差中位数 > --video-motion(默认0.5) 的段是摄像头画面(人坐在一起，
       整屏持续微动; 幻灯片段 ≤0.3)，不截图不入页，只在 slides.json 里留时间线

media 模式（--media / --mode media，面向动态上手/评测视频）：
    动态视频不存在"稳定页面"，改用镜头(shot)原语：全帧差分的局部显著峰
    为切点（自适应阈值 max(8.0, p50×6)），最短镜头 1.5s 并回邻居；每镜头
    取中点帧为代表帧，逐像素中位数签名把重复出现的镜头合并为一页；
    对判定为口播候选的镜头（中心肤色占比 + 低边缘密度的轻量代理），再开
    一条 16×16 dHash 汉明距通道做二次合并——同一主讲人换姿势/手势时全帧
    均差会超阈值，dHash 对构图近重复稳健；口播合并页标 talking_head=true
    且 ranges 累记每次出现区间。内容帧（图表/规格表）维持严格全帧差分不
    走 dHash 通道，不同数据的同版式图表绝不误并。合并不设数量配额，唯一
    判据是信息冗余。去重后超过 80 页按时长择优截断并在 pages.json 标注
    truncated。输出结构与 slides 模式完全兼容（kind 沿用 "slide"，附加
    shot 标记）。

用法：
    bin/slide_pages.py meeting.mp4 --out meetings/<目录>/slides
    bin/slide_pages.py meeting.mp4 --out .../slides --update-minutes .../minutes.md
    bin/slide_pages.py video.mp4 --out .../slides --media

输出：out/page_NN_t<s>.jpg + 同级 slides.json；stdout 只打印元数据。
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np


def _probe_size(video: Path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height", "-of", "csv=p=0",
                          str(video)], capture_output=True, text=True, check=True).stdout
    w, h = out.strip().split(",")[:2]
    return int(w), int(h)


def _suppress_sparse_annotations(rgb: np.ndarray, max_fraction: float = 0.04) -> np.ndarray:
    """将 RGB 帧转灰度，并仅为“页面身份判定”消除稀疏高饱和标注。

    会议中的红框、激光点和彩色鼠标通常是稀疏线条；当高饱和像素
    超过整帧的 max_fraction 时，更可能是彩色图表/实际内容，不做抑制。
    截图仍从原视频抓取，不会被这个预处理改写。
    """
    values = rgb.astype(np.uint16)
    red, green, blue = values[..., 0], values[..., 1], values[..., 2]
    gray = ((77 * red + 150 * green + 29 * blue + 128) >> 8).astype(np.uint8)
    red_mark = (red >= 135) & (red >= green + 42) & (red >= blue + 42)
    green_mark = (green >= 150) & (green >= red + 48) & (green >= blue + 32)
    blue_mark = (blue >= 150) & (blue >= red + 48) & (blue >= green + 32)
    marked = red_mark | green_mark | blue_mark
    fraction = float(marked.mean())
    if not marked.any() or fraction > max_fraction:
        return gray

    # 用 6px 外围邻域的中位数替换线条/光点。偏移大于常见红框线宽，
    # 同时避免引入 OpenCV 依赖。
    offset = 6
    padded = np.pad(gray, offset, mode="edge")
    h, w = gray.shape
    neighbors = np.stack([
        padded[offset + dy:offset + dy + h, offset + dx:offset + dx + w]
        for dy, dx in ((-offset, -offset), (-offset, 0), (-offset, offset),
                       (0, -offset), (0, 0), (0, offset),
                       (offset, -offset), (offset, 0), (offset, offset))
    ])
    replacement = np.median(neighbors, axis=0).astype(np.uint8)
    result = gray.copy()
    result[marked] = replacement[marked]
    return result


def _decode_small(video: Path, fps: float, sw: int, suppress: bool = True,
                  talk_stats: bool = False):
    """低帧率 RGB 流式解码后转为判页灰度帧，避免整段 RGB 常驻内存。

    suppress=False（media 镜头检测）时只做灰度转换，不做幻灯片向的
    稀疏标注抑制。talk_stats=True（media 口播代理）时边解码边逐帧统计
    中心肤色占比与全帧边缘密度，随灰度帧一起返回 (frames, stats)，
    不需要为颜色判定保留整段 RGB。"""
    w, h = _probe_size(video)
    sh = max(2, round(h * sw / w / 2) * 2)
    cmd = ["ffmpeg", "-v", "error", "-i", str(video),
           "-vf", f"fps={fps},scale={sw}:{sh}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frame_bytes = sw * sh * 3
    gray_raw = bytearray()
    skins, edges = [], []
    while True:
        block = bytearray()
        while len(block) < frame_bytes:
            chunk = proc.stdout.read(frame_bytes - len(block)) if proc.stdout else b""
            if not chunk:
                break
            block.extend(chunk)
        if len(block) != frame_bytes:
            break
        rgb = np.frombuffer(block, dtype=np.uint8).reshape(sh, sw, 3)
        if suppress:
            gray = _suppress_sparse_annotations(rgb)
        else:
            v = rgb.astype(np.uint16)
            gray = ((77 * v[..., 0] + 150 * v[..., 1] + 29 * v[..., 2] + 128) >> 8).astype(np.uint8)
        gray_raw.extend(gray.tobytes())
        if talk_stats:
            skins.append(_skin_fraction(rgb))
            edges.append(_edge_density(gray))
    stderr = proc.stderr.read() if proc.stderr else b""
    rc = proc.wait()
    if rc:
        raise subprocess.CalledProcessError(rc, cmd, stderr=stderr)
    n = len(gray_raw) // (sw * sh)
    frames = np.frombuffer(gray_raw, dtype=np.uint8).reshape(n, sh, sw)
    if talk_stats:
        return frames, {"skin": np.array(skins), "edge": np.array(edges)}
    return frames


def _skin_fraction(rgb: np.ndarray) -> float:
    """中心裁切区（中央 50% 宽 × 60% 高）内的肤色像素占比。

    经典 RGB 经验规则，无人脸检测器，只是"口播候选"代理：暗光/侧脸/
    非典型肤色会漏判，肤色相近的产品、背景板会误判。因此它只作为
    dHash 二次合并通道的闸门，不单独决定任何合并。"""
    h, w = rgb.shape[:2]
    crop = rgb[int(h * 0.2):int(h * 0.8), int(w * 0.25):int(w * 0.75)].astype(np.int16)
    r, g, b = crop[..., 0], crop[..., 1], crop[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    skin = (r > 95) & (g > 40) & (b > 20) & ((mx - mn) > 15) & (r > g) & (r > b)
    return float(skin.mean())


def _edge_density(gray: np.ndarray, threshold: int = 24) -> float:
    """全帧边缘密度：强梯度像素占比。文字/图表帧远高于口播特写。"""
    g = gray.astype(np.int16)
    gx = np.abs(np.diff(g, axis=1)) > threshold
    gy = np.abs(np.diff(g, axis=0)) > threshold
    return float((gx.mean() + gy.mean()) / 2)


def _dhash16(gray: np.ndarray, size: int = 16, eps: float = 3.0):
    """16×16 感知哈希（dHash）：面积平均降采样到 size×(size+1)，相邻格亮度
    比较得 size×size 布尔位，返回 (bits, mask)。

    平坡区域相邻格亮度差接近 0，编码噪声会让这些"平局位"随机翻转（实测同
    一构图经不同码率上下文编码后裸汉明距可达 16/256）；因此 |差| ≤ eps
    的位记入 mask=不显著，_hamming 只统计双方都显著的位。对均匀明暗变化
    与轻微位移稳健。"""
    a = np.asarray(gray, dtype=np.float32)
    h, w = a.shape
    rows = np.linspace(0, h, size + 1).astype(int)
    cols = np.linspace(0, w, size + 2).astype(int)
    small = np.empty((size, size + 1), dtype=np.float32)
    for i in range(size):
        for j in range(size + 1):
            small[i, j] = a[rows[i]:rows[i + 1], cols[j]:cols[j + 1]].mean()
    d = small[:, 1:] - small[:, :-1]
    return d > 0, np.abs(d) > eps


def _hamming(a: tuple, b: tuple) -> int:
    """掩码汉明距：只统计两帧都显著(非平局)且结论相反的位。"""
    (bits_a, mask_a), (bits_b, mask_b) = a, b
    return int(np.count_nonzero(mask_a & mask_b & (bits_a != bits_b)))


# 口播代理合并参数（media 模式）：候选闸门 + dHash 汉明距上限。
# 只作用于"两帧都是口播候选"的合并；内容帧永远走严格全帧差分。
_TALK_SKIN_MIN = 0.10   # 中心裁切肤色占比下限
_TALK_EDGE_MAX = 0.12   # 全帧边缘密度上限(文字/图表帧远高于此)
_TALK_DHASH_HAM = 8     # 16×16 dHash(256bit) 掩码汉明距上限, 可用 --talk-ham 调整


def _motion_mask(frames: np.ndarray, keep_pct: float = 80.0,
                 ignore_right_pct: float = 15.0):
    """返回页面内容比较 mask。

    Teams/Zoom 的右侧参会人栏会因加入、离开、开关摄像头而偶发变化；它不是
    持续运动区域，单靠全场 activity 分位无法稳定屏蔽。先显式排除右侧 UI，再
    在剩余内容区屏蔽持续运动像素。截图仍保留完整画面，只影响切页和同页判断。
    """
    f = frames.astype(np.float32)
    activity = np.abs(np.diff(f, axis=0)).mean(axis=0)
    th = np.percentile(activity, keep_pct)
    mask = activity <= th
    ignored = max(0.0, min(45.0, float(ignore_right_pct)))
    content_end = max(1, int(round(mask.shape[1] * (1.0 - ignored / 100.0))))
    mask[:, content_end:] = False
    content_area = mask[:, :content_end]
    if content_area.mean() < 0.1:      # 内容区全屏都在动(纯视频?)→ 只保留显式 ROI
        mask = np.zeros_like(activity, dtype=bool)
        mask[:, :content_end] = True
    return mask


def _masked_diff(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> float:
    d = np.abs(a.astype(np.float32) - b.astype(np.float32))
    return float(d[mask].mean())


def _content_roi(shape: tuple[int, int], ignore_right_pct: float = 15.0) -> np.ndarray:
    """只排除会议 UI 右栏的显式内容 ROI；用于标题区，不受全场 activity 屏蔽影响。"""
    h, w = shape
    ignored = max(0.0, min(45.0, float(ignore_right_pct)))
    end = max(1, int(round(w * (1.0 - ignored / 100.0))))
    roi = np.zeros((h, w), dtype=bool)
    roi[:, :end] = True
    return roi


def _trimmed_mean(values: np.ndarray, upper_fraction: float = 0.01) -> float:
    """丢掉最强的少量差异，避免白色鼠标等非彩色小物体主导标题区。"""
    flat = np.asarray(values, dtype=np.float32).reshape(-1)
    if not len(flat):
        return 0.0
    keep = max(1, int(round(len(flat) * (1.0 - upper_fraction))))
    if keep >= len(flat):
        return float(flat.mean())
    return float(np.partition(flat, keep - 1)[:keep].mean())


def _page_diff(a: np.ndarray, b: np.ndarray, stable_mask: np.ndarray,
               content_roi: np.ndarray, title_fraction: float = 0.22) -> float:
    """页面身份距离：全页用稳定像素，标题区用显式 ROI 并增强灵敏度。"""
    delta = np.abs(a.astype(np.float32) - b.astype(np.float32))
    whole = float(delta[stable_mask].mean()) if stable_mask.any() else 0.0
    title_rows = max(1, int(round(delta.shape[0] * title_fraction)))
    title_mask = content_roi.copy()
    title_mask[title_rows:, :] = False
    title = _trimmed_mean(delta[title_mask], upper_fraction=0.01)
    return max(whole, title)


def _segments(dist: np.ndarray, threshold: float, min_len: int):
    """距离序列 → 帧段 [(s,e)]；短段并回邻居。"""
    bounds = [i + 1 for i, d in enumerate(dist) if d > threshold]
    cuts = [0] + bounds + [len(dist) + 1]
    segs = [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]
    changed = True
    while changed and len(segs) > 1:
        changed = False
        for i, (s, e) in enumerate(segs):
            if e - s < min_len:
                if i == 0:
                    segs[1] = (s, segs[1][1])
                else:
                    segs[i - 1] = (segs[i - 1][0], e)
                del segs[i]
                changed = True
                break
    return segs


def _grab_frame(video: Path, t: float, width: int, out: Path):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
                    "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(out)],
                   check=True)


def _shot_thresholds(dist: np.ndarray) -> tuple[float, float]:
    """media 模式自适应阈值：切点 = max(8.0, 基线 p50×6)，同镜头 = max(4.0, p50×2)。

    镜头内连续运动构成基线(取中位数, 抗切点尖峰污染)；硬切的全帧差分通常
    远高于基线，绝对下限防止全程静止时阈值塌到 0。
    """
    base = float(np.median(dist))
    return max(8.0, base * 6.0), max(4.0, base * 2.0)


def _shot_cuts(dist: np.ndarray, threshold: float) -> list[int]:
    """全帧差分的局部显著峰 → 切点帧号（峰不劣于左邻且严格高于右邻）。"""
    cuts = []
    for i, d in enumerate(dist):
        if d <= threshold:
            continue
        left = dist[i - 1] if i else -1.0
        right = dist[i + 1] if i + 1 < len(dist) else -1.0
        if d >= left and d > right:
            cuts.append(i + 1)
    return cuts


def _extract_shots(video, out_dir, pages_json=None, *, fps=1.0, width=1280,
                   threshold=None, same_threshold=None, min_shot_sec=1.5,
                   max_pages=80, talk_ham=_TALK_DHASH_HAM, verbose=True):
    """动态视频 → 镜头(shot)抽取：全帧差分局部峰切点 + 中位数签名去重。

    合并双通道：内容帧维持严格全帧差分（阈值 th_same，防误并同版式不同
    数据的图表）；两帧都是口播候选（中心肤色占比 ≥_TALK_SKIN_MIN 且全帧
    边缘密度 ≤_TALK_EDGE_MAX）时，再允许 16×16 dHash 汉明距 ≤talk_ham
    合并——主讲人换姿势/手势的全帧均差会超 th_same，但构图仍近重复。
    口播合并页标 talking_head=true 供 UI 折叠展示，ranges 累记每次出现
    区间。合并只消信息冗余，不设数量配额。
    不做 slide 向的 ROI/稀疏标注抑制；输出结构与 extract_pages 的 slides
    模式完全兼容（kind 沿用 "slide"，附加 shot=True 标记），下游 VL/纪要/
    导出无需改动。
    """
    video, out_dir = Path(video), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("page_*.jpg"):
        old.unlink()

    frames, talk = _decode_small(video, fps, 320, suppress=False, talk_stats=True)
    n = len(frames)
    if n < 2:
        return []
    f32 = frames.astype(np.float32)
    dist = np.abs(f32[1:] - f32[:-1]).mean(axis=(1, 2))
    th, th_same = _shot_thresholds(dist)
    if threshold is not None:
        th = threshold
    if same_threshold is not None:
        th_same = same_threshold
    cuts = _shot_cuts(dist, th)
    # 复用 slides 的短段并回邻居逻辑：只让显著峰越过阈值
    peaks = np.zeros(len(dist))
    for c in cuts:
        peaks[c - 1] = dist[c - 1]
    min_len = max(1, int(round(min_shot_sec * fps)))
    segs = _segments(peaks, th, min_len)

    shots = []  # {page, first, image, sig, captured, ranges, talk, dhash}
    for s, e in segs:
        t0, t1 = s / fps, e / fps
        sig = np.median(f32[s:e], axis=0)
        cand = (float(np.median(talk["skin"][s:e])) >= _TALK_SKIN_MIN
                and float(np.median(talk["edge"][s:e])) <= _TALK_EDGE_MAX)
        dh = _dhash16(sig) if cand else None
        hit = None
        for p in shots:                                  # 通道一：严格全帧差分
            if float(np.abs(sig - p["sig"]).mean()) < th_same:
                hit = p
                break
        if hit is None and cand:                         # 通道二：口播 dHash
            for p in shots:
                if p["talk"] and _hamming(dh, p["dhash"]) <= talk_ham:
                    hit = p
                    break
        if hit is None:
            num = len(shots) + 1
            img = out_dir / f"page_{num:02d}_t{int(round(t0)):04d}s.jpg"
            mid = (s + e - 1) // 2                      # 镜头中点帧为代表帧
            t_cap = min((mid + 0.5) / fps, n / fps - 1.0)  # 不越出片尾
            try:
                _grab_frame(video, t_cap, width, img)
            except subprocess.CalledProcessError:           # 片尾边界再退一步
                _grab_frame(video, max(0.0, t_cap - 2.0), width, img)
            shots.append({"page": num, "first": round(t0, 1), "image": img,
                          "sig": sig, "captured": round(t_cap, 1),
                          "ranges": [[round(t0, 1), round(t1, 1)]],
                          "talk": cand, "dhash": dh})
        else:
            hit["ranges"].append([round(t0, 1), round(t1, 1)])

    # 上限保护：去重后仍超 max_pages 时，保留总时长最长、覆盖最广的镜头
    truncated = len(shots) > max_pages
    if truncated:
        shots.sort(key=lambda p: -sum(re - rs for rs, re in p["ranges"]))
        for p in shots[max_pages:]:                 # 被截镜头的截图一并清除
            p["image"].unlink(missing_ok=True)
        del shots[max_pages:]
        shots.sort(key=lambda p: p["first"])
        for num, p in enumerate(shots, 1):              # 重排页码与截图文件名
            if p["page"] != num:
                new_img = p["image"].with_name(f"page_{num:02d}{p['image'].name[7:]}")
                p["image"].rename(new_img)
                p["image"] = new_img
                p["page"] = num

    n_talk = sum(1 for p in shots if p["talk"])
    if verbose:
        print(f"[meta] 镜头抽取: {n} 采样帧 | 切点阈值 {th:.2f}(基线 {float(np.median(dist)):.2f})"
              f" | 镜头 {len(segs)} | 去重后 {len(shots)} 页(口播 {n_talk})"
              + (f" | 超上限截断(≤{max_pages})" if truncated else ""), flush=True)
    out_pages = [{"page": p["page"], "first": p["first"], "image": p["image"],
                  "captured": p["captured"], "ranges": p["ranges"],
                  "talking_head": p["talk"]} for p in shots]
    pj = Path(pages_json) if pages_json else out_dir.parent / "slides.json"
    timeline = []
    for p in out_pages:
        entry = {"kind": "slide", "page": p["page"], "first": p["first"],
                 "image": p["image"].name, "captured": p["captured"],
                 "ranges": p["ranges"], "shot": True}
        if p["talking_head"]:
            entry["talking_head"] = True
        timeline.append(entry)
    if truncated:
        for entry in timeline:
            entry["truncated"] = True
    timeline.sort(key=lambda x: x["first"])
    pj.write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_pages


def extract_pages(video, out_dir, pages_json=None, fps=1.0, width=1280,
                  min_seg_sec=2.0, threshold=None, same_threshold=None,
                  keep_pct=80.0, video_motion=0.5, verbose=True,
                  ignore_right_pct=15.0, mode="slides", min_shot_sec=1.5,
                  max_pages=80, talk_ham=_TALK_DHASH_HAM):
    """返回 [{page, first, image(Path), ranges:[[s,e],...]}]，按首次出现排序。

    mode="slides"（默认，会议录屏）：段内帧间差中位数 > video_motion 的段判为
    摄像头画面(人坐在一起：整屏持续微动，幻灯片段核心区域静止, 该值一般 ≤0.3)，
    不截图、不入页，只记入 slides.json。
    mode="media"（动态视频）：按镜头切分，见 _extract_shots。
    """
    if mode == "media":
        return _extract_shots(video, out_dir, pages_json, fps=fps, width=width,
                              threshold=threshold, same_threshold=same_threshold,
                              min_shot_sec=min_shot_sec, max_pages=max_pages,
                              talk_ham=talk_ham, verbose=verbose)
    if mode != "slides":
        raise ValueError(f"未知抽取模式: {mode}")
    video, out_dir = Path(video), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("page_*.jpg"):
        old.unlink()

    frames = _decode_small(video, fps, 320)
    n = len(frames)
    if n < 2:
        return []
    mask = _motion_mask(frames, keep_pct, ignore_right_pct)
    content_roi = _content_roi(frames.shape[1:], ignore_right_pct)
    dist = np.array([_page_diff(frames[i], frames[i + 1], mask, content_roi)
                     for i in range(n - 1)])
    # 自适应下限：静态噪声(p90≈0.3)与真变化(≥3)之间空档很宽；全程静态时无切点=单页
    th = threshold if threshold is not None else max(2.0, float(np.percentile(dist, 90)) * 5)
    th_same = same_threshold if same_threshold is not None else max(1.0, th / 2)
    min_len = max(1, int(round(min_seg_sec * fps)))
    segs = _segments(dist, th, min_len)

    pages = []  # {page, first, image, sig, ranges}
    cams = []   # 摄像头画面时间段(合并相邻)
    for s, e in segs:
        t0, t1 = s / fps, e / fps
        motion = float(np.median(dist[s:max(s + 1, e - 1)]))
        if motion > video_motion:
            if cams and cams[-1]["ranges"][-1][1] == round(t0, 1):
                cams[-1]["ranges"][-1][1] = round(t1, 1)
            else:
                cams.append({"kind": "camera", "first": round(t0, 1),
                             "ranges": [[round(t0, 1), round(t1, 1)]]})
            continue
        sig = np.median(frames[s:e], axis=0)
        # medoid 截图：取与段签名最接近的一帧。段末帧可能被并入的 1-2s 杂质帧
        # (共享闪断/黑帧) 污染——杂质时长 <50% 时 medoid 必然落在主状态上
        d2sig = np.abs(frames[s:e].astype(np.float32) - sig)[:, mask].mean(axis=1)
        cap_f = s + int(np.argmin(d2sig))
        hit = None
        for p in pages:
            if _page_diff(sig, p["sig"], mask, content_roi) < th_same:
                hit = p
                break
        if hit is None:
            num = len(pages) + 1
            img = out_dir / f"page_{num:02d}_t{int(round(t0)):04d}s.jpg"
            t_cap = min((cap_f + 0.5) / fps, n / fps - 1.0)   # 不越出片尾
            try:
                _grab_frame(video, t_cap, width, img)
            except subprocess.CalledProcessError:             # 片尾边界再退一步
                _grab_frame(video, max(0.0, t_cap - 2.0), width, img)
            pages.append({"page": num, "first": round(t0, 1), "image": img,
                          "sig": sig, "captured": round(t_cap, 1),
                          "ranges": [[round(t0, 1), round(t1, 1)]]})
        else:
            hit["ranges"].append([round(t0, 1), round(t1, 1)])

    if verbose:
        print(f"[meta] 抽页: {n} 采样帧 | 内容区右侧排除 {ignore_right_pct:.0f}%"
              f" | 阈值 {th:.2f}(同页 {th_same:.2f})"
              f" | 稳定段 {len(segs)} | 逻辑页 {len(pages)}"
              f" | 摄像头画面段 {sum(len(c['ranges']) for c in cams)} 个已跳过", flush=True)
    out_pages = [{"page": p["page"], "first": p["first"], "image": p["image"],
                  "captured": p["captured"], "ranges": p["ranges"]} for p in pages]
    pj = Path(pages_json) if pages_json else out_dir.parent / "slides.json"
    timeline = [{"kind": "slide", "page": p["page"], "first": p["first"],
                 "image": p["image"].name, "captured": p["captured"],
                 "ranges": p["ranges"]} for p in out_pages]
    timeline += cams
    timeline.sort(key=lambda x: x["first"])
    pj.write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_pages


def _to_sec(ts: str) -> float:
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return int(parts[0]) * 60 + float(parts[1])


def _mmss(sec: float) -> str:
    s = int(sec)
    return f"{s//60:02d}:{s%60:02d}"


def page_at(pages, t: float):
    """时间 t 正在显示哪页：先找包含 t 的时间段，找不到取最近的前置页。"""
    best = None
    for p in pages:
        for s, e in p["ranges"]:
            if s <= t <= e:
                return p
            if e <= t and (best is None or e > best[1]):
                best = (p, e)
    return best[0] if best else (pages[0] if pages else None)


def attach_slides(minutes: str, pages, mdir: Path) -> str:
    """议题标题带 [mm:ss] 的，按时间线插入"当时显示的那页"；否则附录页码画廊。"""
    mdir = Path(mdir)
    if not pages:
        return minutes
    used, out = set(), []
    for ln in minutes.splitlines():
        out.append(ln)
        m = re.match(r"\s*#{2,4}.*?\[(\d{1,2}:\d{2}(?::\d{2})?)\]", ln)
        if m:
            p = page_at(pages, _to_sec(m.group(1)))
            if p is not None and str(p["image"]) not in used:
                used.add(str(p["image"]))
                rel = p["image"].relative_to(mdir)
                out.append(f"\n![第{p['page']}页 {_mmss(p['first'])}]({rel})\n")
    if not used:
        out.append("\n## 幻灯片页码索引\n")
        for p in pages:
            out.append(f"- 第{p['page']}页 [{_mmss(p['first'])}] ![]({p['image'].relative_to(mdir)})")
    return "\n".join(out) + "\n"


def update_minutes(minutes_path: Path, pages, mdir: Path):
    """去掉纪要里旧的截图行，按新时间线重新贴图。"""
    text = Path(minutes_path).read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines()
             if not re.search(r"!\[[^\]]*\]\((?:assets/[^)]*/|slides/)", ln)]
    text = "\n".join(lines).strip() + "\n"
    text = attach_slides(text, pages, mdir)
    Path(minutes_path).write_text(text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="录屏 → 逻辑页抽取(稳定段+运动屏蔽+页码时间线)；"
                                 "media 模式按镜头切分动态视频")
    ap.add_argument("video", type=Path)
    ap.add_argument("--out", type=Path, required=True, help="截图输出目录(会议目录/slides)")
    ap.add_argument("--pages-json", type=Path, default=None, help="默认 <out 同级>/slides.json")
    ap.add_argument("--update-minutes", type=Path, default=None, help="重贴纪要里的截图")
    ap.add_argument("--mode", choices=["slides", "media"], default="slides",
                    help="slides=会议录屏稳定页(默认)；media=动态视频镜头检测")
    ap.add_argument("--media", action="store_true", help="等同 --mode media")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--min-seg", type=float, default=2.0)
    ap.add_argument("--min-shot", type=float, default=1.5, help="media 最短镜头秒数, 过短并回邻居")
    ap.add_argument("--max-pages", type=int, default=80, help="media 去重后页数上限, 超出按时长截断")
    ap.add_argument("--talk-ham", type=int, default=_TALK_DHASH_HAM,
                    help="media 口播候选 dHash 合并的汉明距上限(16×16=256bit)")
    ap.add_argument("--threshold", type=float, default=None,
                    help="翻页/切点阈值(slides 默认 max(2.0, p90×5), media 默认 max(8.0, p50×6))")
    ap.add_argument("--same-threshold", type=float, default=None, help="同页/同镜头阈值(默认自适应)")
    ap.add_argument("--keep-pct", type=float, default=80.0, help="参与比较的静态像素分位")
    ap.add_argument("--ignore-right-pct", type=float, default=15.0,
                    help="忽略右侧会议 UI/参会人栏宽度百分比；0 表示不忽略")
    ap.add_argument("--video-motion", type=float, default=0.5,
                    help="段内运动中位数超过此值判为摄像头画面(人坐一起), 不截图")
    args = ap.parse_args()

    if not args.video.is_file():
        print(f"找不到视频: {args.video}", file=sys.stderr)
        return 1
    mode = "media" if args.media else args.mode
    pages = extract_pages(args.video, args.out, args.pages_json, args.fps, args.width,
                          args.min_seg, args.threshold, args.same_threshold, args.keep_pct,
                          args.video_motion, ignore_right_pct=args.ignore_right_pct,
                          mode=mode, min_shot_sec=args.min_shot, max_pages=args.max_pages,
                          talk_ham=args.talk_ham)
    if args.update_minutes and pages:
        update_minutes(args.update_minutes, pages, Path(args.update_minutes).parent)
        print(f"[meta] 已重贴纪要截图: {args.update_minutes}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
