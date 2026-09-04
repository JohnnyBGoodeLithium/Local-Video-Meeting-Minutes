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

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
from meeting_artifact import load_speaker_profiles, write_evidence_document  # noqa: E402
import meeting_topic_map  # noqa: E402

ROOT = Path(os.environ.get("MM_TEST_ROOT", Path(__file__).resolve().parents[2])).resolve()
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
     "text": "This is synthetic data for the first review."},
    {"speaker": "Alice", "voice": "v_9001", "start": 6.5, "end": 10.0,
     "text": "假数据，the second review round结束。"},
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
Image.new("RGB", (1920, 1080), (210, 210, 210)).save(mdir / "slides" / "full_01.jpg")

minutes = """# 会议纪要

## 总体摘要

- **主旨**：合成夹具，无真实内容。 <!-- mm:evidence kind=purpose status=informational confidence=high turns=T000001,T000002 pages=P0001 -->

## 议题板块

- 假板块（第1–2页，00:00 起）：夹具。

## 分页详情

### 第1页 [00:00] 假页面一

![第1页](slides/page1.png)

- **本页结论**：未形成结论
- 讨论了第一轮假数据。 <!-- mm:evidence kind=discussion status=informational confidence=high turns=T000001,T000002 pages=P0001 -->

### 第2页 [00:05] 假页面二

![第2页](slides/page2.png)

- **本页结论**：未形成结论
- **决定**：结束本次合成评审。 <!-- mm:evidence kind=decision status=informational confidence=high turns=T000003 pages=P0002 -->
"""
(mdir / "minutes.md").write_text(minutes, encoding="utf-8")

page_desc = {"model": "synthetic-vl", "desc": {
    "1": "<think>这是不应进入导出包的合成推理</think>\n# 标题\n合成页面一。页面展示蓝色测试背景，不代表会议结论。",
    "2": "# 标题\n合成页面二。页面展示绿色测试背景，仅供页面检索。",
}}
(mdir / "page_desc.json").write_text(json.dumps(page_desc, ensure_ascii=False, indent=1),
                                      encoding="utf-8")

for name in ("Alice", "Bob"):
    sf.write(str(mdir / "samples" / f"{name}.wav"), np.zeros(SR, dtype=np.float32), SR)

(mdir / "source.json").write_text(json.dumps(
    {"wav": str(mdir / "audio.wav")}, ensure_ascii=False, indent=1), encoding="utf-8")

bank_dir = Path(os.environ.get("MM_TEST_BANK", "/tmp/mm_fake_bank"))
profiles = load_speaker_profiles(turns, bank_dir)
_, evidence = write_evidence_document(
    mdir, minutes, turns, slides, {1: page_desc["desc"]["1"], 2: page_desc["desc"]["2"]}, profiles,
    generation={"synthetic_fixture": True})

raw_topic_map = {
    "meeting_summary": "合成会议依次完成开场、第一轮评审和第二轮收束。",
    "topics": [
        {"title": "明确评审范围", "summary": "先确认本次合成评审的目标。",
         "turn_ids": ["T000001"], "claim_ids": ["C00001"], "page_ids": ["P0001"],
         "children": [
             {"type": "context", "title": "评审开场", "summary": "说明会议目的。",
              "turn_ids": ["T000001"], "claim_ids": ["C00001"], "page_ids": ["P0001"]},
             {"type": "discussion", "title": "进入评审", "summary": "开始核对第一轮内容。",
              "turn_ids": ["T000001"], "claim_ids": [], "page_ids": ["P0001"]}]},
        {"title": "完成第一轮评审", "summary": "围绕第一轮合成数据进行检查。",
         "turn_ids": ["T000002"], "claim_ids": ["C00002"], "page_ids": ["P0001"],
         "children": [
             {"type": "argument", "title": "第一轮内容", "summary": "说明第一轮评审对象。",
              "turn_ids": ["T000002"], "claim_ids": ["C00002"], "page_ids": ["P0001"]},
             {"type": "evidence", "title": "对应画面", "summary": "页面一作为背景资料。",
              "turn_ids": ["T000002"], "claim_ids": [], "page_ids": ["P0001"]}]},
        {"title": "第二轮收束", "summary": "切换到第二轮并结束合成会议。",
         "turn_ids": ["T000003"], "claim_ids": ["C00003"], "page_ids": ["P0002"],
         "children": [
             {"type": "decision", "title": "评审结束", "summary": "第二轮完成后收束会议。",
              "turn_ids": ["T000003"], "claim_ids": ["C00003"], "page_ids": ["P0002"]},
             {"type": "evidence", "title": "第二页资料", "summary": "页面二辅助定位收束阶段。",
              "turn_ids": ["T000003"], "claim_ids": [], "page_ids": ["P0002"]}]},
    ],
}
topic_map = meeting_topic_map._sanitize_map(
    raw_topic_map, evidence, meeting_topic_map.current_revisions(mdir),
    model="synthetic", window_count=1, chunk_seconds=480.0)
(mdir / "meeting.topic-map.json").write_text(
    json.dumps(topic_map, ensure_ascii=False, indent=1), encoding="utf-8")

print("smoke fixture ok:", sorted(p.name for p in mdir.iterdir()))
