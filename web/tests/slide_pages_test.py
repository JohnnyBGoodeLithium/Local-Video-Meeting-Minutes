#!/usr/bin/env python3
"""验证页面身份：忽略参会人/标注，但保留大标题变化（全合成像素）。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
from slide_pages import (  # noqa: E402
    _content_roi,
    _masked_diff,
    _motion_mask,
    _page_diff,
    _segments,
    _suppress_sparse_annotations,
)


frames = np.full((6, 40, 100), 40, dtype=np.uint8)
# 右侧参会人栏三次变化；页面内容不变。
frames[1, :, 88:] = 210
frames[2, :, 88:] = 90
frames[3, :, 88:] = 180
frames[4, :, 88:] = 70
frames[5, :, 88:] = 150

mask = _motion_mask(frames, keep_pct=100, ignore_right_pct=15)
assert not mask[:, 85:].any()
dist = np.array([_masked_diff(frames[i], frames[i + 1], mask)
                 for i in range(len(frames) - 1)])
assert float(dist.max()) == 0
assert _segments(dist, threshold=2, min_len=1) == [(0, 6)]

# 真正的页面主体变化仍必须切段。
frames[3:, :, :70] = 120
mask = _motion_mask(frames, keep_pct=100, ignore_right_pct=15)
dist = np.array([_masked_diff(frames[i], frames[i + 1], mask)
                 for i in range(len(frames) - 1)])
segments = _segments(dist, threshold=2, min_len=1)
assert segments == [(0, 3), (3, 6)]

# 同一张表格上的红框、激光点只是讲解状态，不是新页。
rgb = np.full((48, 120, 3), 245, dtype=np.uint8)
rgb[12:14, 8:95] = 35                       # 表头
rgb[18:40:6, 8:95] = 70                    # 表格行
rgb[4:6, 8:14] = 30                        # 大标题 A（稀疏文字笔画）
annotated = rgb.copy()
annotated[23:25, 42:78] = (235, 20, 20)    # 红框上/下边
annotated[34:36, 42:78] = (235, 20, 20)
annotated[23:36, 42:44] = (235, 20, 20)
annotated[23:36, 76:78] = (235, 20, 20)
annotated[16:19, 102:105] = (255, 10, 10)  # 激光点
base_gray = _suppress_sparse_annotations(rgb)
annotation_gray = _suppress_sparse_annotations(annotated)
roi = _content_roi(base_gray.shape, ignore_right_pct=15)
stable = roi.copy()
assert _page_diff(base_gray, annotation_gray, stable, roi) < 2.0

# 表格主体不变，但顶部大标题改变：必须识别成新页。
title_b = rgb.copy()
title_b[4:6, 8:14] = 245
title_b[4:6, 54:60] = 30                   # 大标题 B
title_b_gray = _suppress_sparse_annotations(title_b)
assert _masked_diff(base_gray, title_b_gray, stable) < 2.0  # 旧全局均值会漏掉
assert _page_diff(base_gray, title_b_gray, stable, roi) > 2.0
title_dist = np.array([
    _page_diff(frame_a, frame_b, stable, roi)
    for frame_a, frame_b in zip(
        [base_gray, base_gray, base_gray, title_b_gray, title_b_gray],
        [base_gray, base_gray, title_b_gray, title_b_gray, title_b_gray],
    )
])
assert _segments(title_dist, threshold=2.0, min_len=1) == [(0, 3), (3, 6)]

print("Slide pages: participant/annotations ignored, title identity preserved")
