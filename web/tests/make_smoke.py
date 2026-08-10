#!/usr/bin/env python3
"""生成合成测试夹具 meetings/_smoke/（全虚构数据，可重复执行：先整目录删除重建）。

配合 web/tests/smoke_test.py 的断言：
- audio.wav 10s 静音; 3 轮转写(v_9001×2 / v_9002×1), 末轮 end=10.0
- slides.json 恰好 2 页; slides/page1.png page2.png
- minutes.md 恰好 2 个带 [mm:ss] 的标题 + slides/ 图片链接
- samples/Alice.wav Bob.wav; source.json 指向本目录 wav(无 mp4 → has_video False)
"""
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image

ROOT = Path(os.environ.get("MM_TEST_ROOT", "/home/johnny-tcx_ultra/meeting-minutes")).resolve()
mdir = ROOT / "meetings" / "_smoke"
SR = 16000

if mdir.exists():
    shutil.rmtree(mdir)
(mdir / "slides").mkdir(parents=True)
(mdir / "samples").mkdir()

sf.write(str(mdir / "audio.wav"), np.zeros(10 * SR, dtype=np.float32), SR)

turns = [
    {"speaker": "Alice", "voice": "v_9001", "start": 0.5, "end": 3.0,
     "text": "大家好，我们开始评审。"},
    {"speaker": "Bob", "voice": "v_9002", "start": 3.5, "end": 6.0,
     "text": "这是假数据，第一轮发言。"},
    {"speaker": "Alice", "voice": "v_9001", "start": 6.5, "end": 10.0,
     "text": "假数据，第二轮发言，结束。"},
]
(mdir / "transcript.spk.json").write_text(
    json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")
md = ["# _smoke 逐字稿(具名)", ""]
md += [f"[{int(t['start']//60):02d}:{int(t['start']%60):02d}] **{t['speaker']}**: {t['text']}"
       for t in turns]
(mdir / "transcript.spk.md").write_text("\n\n".join(md) + "\n", encoding="utf-8")

slides = [
    {"kind": "slide", "page": 1, "first": 0.0, "captured": 0.5, "image": "page1.png",
     "ranges": [[0.0, 5.0]]},
    {"kind": "slide", "page": 2, "first": 5.0, "captured": 5.5, "image": "page2.png",
     "ranges": [[5.0, 10.0]]},
]
(mdir / "slides.json").write_text(json.dumps(slides, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
for i, color in ((1, (200, 220, 255)), (2, (220, 255, 220))):
    Image.new("RGB", (320, 180), color).save(mdir / "slides" / f"page{i}.png")

minutes = """# 会议纪要

## 总体摘要

- **主旨**：合成夹具，无真实内容。

## 议题板块

- 假板块（第1–2页，00:00 起）：夹具。

## 分页详情

### 第1页 [00:00] 假页面一

![第1页](slides/page1.png)

- **本页结论**：未形成结论

### 第2页 [00:05] 假页面二

![第2页](slides/page2.png)

- **本页结论**：未形成结论
"""
(mdir / "minutes.md").write_text(minutes, encoding="utf-8")

for name in ("Alice", "Bob"):
    sf.write(str(mdir / "samples" / f"{name}.wav"), np.zeros(SR, dtype=np.float32), SR)

(mdir / "source.json").write_text(json.dumps(
    {"wav": str(mdir / "audio.wav")}, ensure_ascii=False, indent=1), encoding="utf-8")

print("smoke fixture ok:", sorted(p.name for p in mdir.iterdir()))
