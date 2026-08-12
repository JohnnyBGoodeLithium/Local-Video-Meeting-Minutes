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

用法：
    bin/slide_pages.py meeting.mp4 --out meetings/<目录>/slides
    bin/slide_pages.py meeting.mp4 --out .../slides --update-minutes .../minutes.md

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


def _decode_small(video: Path, fps: float, sw: int):
    """低帧率 RGB 流式解码后转为判页灰度帧，避免整段 RGB 常驻内存。"""
    w, h = _probe_size(video)
    sh = max(2, round(h * sw / w / 2) * 2)
    cmd = ["ffmpeg", "-v", "error", "-i", str(video),
           "-vf", f"fps={fps},scale={sw}:{sh}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frame_bytes = sw * sh * 3
    gray_raw = bytearray()
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
        gray_raw.extend(_suppress_sparse_annotations(rgb).tobytes())
    stderr = proc.stderr.read() if proc.stderr else b""
    rc = proc.wait()
    if rc:
        raise subprocess.CalledProcessError(rc, cmd, stderr=stderr)
    n = len(gray_raw) // (sw * sh)
    return np.frombuffer(gray_raw, dtype=np.uint8).reshape(n, sh, sw)


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


def extract_pages(video, out_dir, pages_json=None, fps=1.0, width=1280,
                  min_seg_sec=2.0, threshold=None, same_threshold=None,
                  keep_pct=80.0, video_motion=0.5, verbose=True,
                  ignore_right_pct=15.0):
    """返回 [{page, first, image(Path), ranges:[[s,e],...]}]，按首次出现排序。

    段内帧间差中位数 > video_motion 的段判为摄像头画面(人坐在一起：整屏持续微动，
    幻灯片段核心区域静止, 该值一般 ≤0.3)，不截图、不入页，只记入 slides.json。
    """
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
    ap = argparse.ArgumentParser(description="录屏 → 逻辑页抽取(稳定段+运动屏蔽+页码时间线)")
    ap.add_argument("video", type=Path)
    ap.add_argument("--out", type=Path, required=True, help="截图输出目录(会议目录/slides)")
    ap.add_argument("--pages-json", type=Path, default=None, help="默认 <out 同级>/slides.json")
    ap.add_argument("--update-minutes", type=Path, default=None, help="重贴纪要里的截图")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--min-seg", type=float, default=2.0)
    ap.add_argument("--threshold", type=float, default=None, help="翻页阈值(默认 max(2.0, p90×5) 自适应)")
    ap.add_argument("--same-threshold", type=float, default=None, help="同页阈值(默认翻页/2)")
    ap.add_argument("--keep-pct", type=float, default=80.0, help="参与比较的静态像素分位")
    ap.add_argument("--ignore-right-pct", type=float, default=15.0,
                    help="忽略右侧会议 UI/参会人栏宽度百分比；0 表示不忽略")
    ap.add_argument("--video-motion", type=float, default=0.5,
                    help="段内运动中位数超过此值判为摄像头画面(人坐一起), 不截图")
    args = ap.parse_args()

    if not args.video.is_file():
        print(f"找不到视频: {args.video}", file=sys.stderr)
        return 1
    pages = extract_pages(args.video, args.out, args.pages_json, args.fps, args.width,
                          args.min_seg, args.threshold, args.same_threshold, args.keep_pct,
                          args.video_motion, ignore_right_pct=args.ignore_right_pct)
    if args.update_minutes and pages:
        update_minutes(args.update_minutes, pages, Path(args.update_minutes).parent)
        print(f"[meta] 已重贴纪要截图: {args.update_minutes}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
