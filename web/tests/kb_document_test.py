#!/usr/bin/env python3
"""知识库导出文档（kb document）与 kbpack 打包：全虚构数据断言。

覆盖：front matter（title/date/content_type/duration/keywords 带 kind/source_url）、
时间码深链格式（含小数秒）、完整视频/音频与屏幕图外链、依据标记保留 #mm-C 纯文本、
VL 描述标题抹平、缺板块降级、英文纪要语言跟随、build_kb_pack 单/多场结构与
kb-pack/v1 manifest、贯穿关键字文字版 index.md，以及 WeKnora 图文 HTML 的
base64 JPEG、低价值帧过滤和单文件命名。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
import kb_document  # noqa: E402
import meeting_topic_map  # noqa: E402
from meeting_artifact import load_speaker_profiles, write_evidence_document  # noqa: E402
from meeting_core import photos as meeting_photos  # noqa: E402

BASE = "http://kb.test"

MINUTES = """# 会议纪要

## 总体摘要

- **主旨**：合成评审，无真实内容。 <!-- mm:evidence kind=purpose status=informational confidence=high turns=T000001 pages=P0001 -->
- **关键结论**：
  1. 先做试点仍是提议。 <!-- mm:evidence kind=alignment status=proposal confidence=high turns=T000002 pages=P0001 -->
  2. 下周再确认最终方案。 <!-- mm:evidence kind=decision status=open confidence=medium turns=T000003 pages=P0002 -->

### 待办事项

| 事项 | 负责人 | 期限 | 状态 |
| --- | --- | --- | --- |
| 完成试点方案 <!-- mm:evidence kind=action status=open confidence=high turns=T000003 --> | 王虚构 | 下周 | 待确认 |

### 风险/待确认

- 合成风险一条，无真实内容。

## 议题板块

- 假板块（第1–2页，00:00 起）：夹具。

## 分页详情

### 第1页 [00:00] 假页面一

- 逐页过程记录，不进入阅读版。
"""

TURNS = [
    {"speaker": "Alice", "voice": "v_8001", "start": 0.5, "end": 3.0,
     "text": "大家好，我们开始合成评审。"},
    {"speaker": "Bob", "voice": "v_8002", "start": 3.5, "end": 6.0,
     "text": "This turn is synthetic."},
    {"speaker": "Carol", "voice": "v_8003", "start": 65.5, "end": 70.0,
     "text": "小数秒时间码轮次，合成内容。"},
]

SLIDES = [
    {"kind": "slide", "page": 1, "first": 0.0, "captured": 0.5, "image": "page1.png",
     "ranges": [[0.0, 5.0]]},
    {"kind": "slide", "page": 2, "first": 65.0, "captured": 65.5, "image": "page2.png",
     "ranges": [[65.0, 70.0]]},
]

PAGE_DESC = {"model": "synthetic-vl", "desc": {
    "1": "<think>合成推理，不进入导出</think>\n# 标题\n合成页面一。蓝色测试背景。",
    "2": "# 标题\n合成页面二。绿色测试背景。",
}}


def make_meeting(root: Path, slug: str, *, full: bool = True) -> Path:
    """造一场合成会议；full=False 时只有纪要+逐字稿，用于缺板块降级断言。"""
    mdir = root / slug
    (mdir / "slides").mkdir(parents=True)
    (mdir / "transcript.spk.json").write_text(
        json.dumps(TURNS, ensure_ascii=False), encoding="utf-8")
    (mdir / "minutes.md").write_text(MINUTES, encoding="utf-8")
    if not full:
        return mdir
    (mdir / "slides.json").write_text(
        json.dumps(SLIDES, ensure_ascii=False), encoding="utf-8")
    for i, color in ((1, (200, 220, 255)), (2, (220, 255, 220))):
        Image.new("RGB", (320, 180), color).save(mdir / "slides" / f"page{i}.png")
    (mdir / "page_desc.json").write_text(
        json.dumps(PAGE_DESC, ensure_ascii=False), encoding="utf-8")
    (mdir / "source_video.mp4").write_bytes(b"synthetic")
    (mdir / "audio.wav").write_bytes(b"synthetic")
    (mdir / "meta.json").write_text(json.dumps(
        {"title": "Alpha 合成评审", "content_type": "meeting",
         "source_url": "https://example.invalid/synthetic-source"},
        ensure_ascii=False), encoding="utf-8")
    revision = hashlib.sha256(MINUTES.encode("utf-8")).hexdigest()[:16]
    (mdir / "meeting.keywords.json").write_text(json.dumps({
        "schema": "meeting-keywords/v1", "status": "complete",
        "source_revision": revision, "facts_revision": None,
        "language": "zh-CN", "model": "synthetic", "updated_at": 1000.0,
        "keywords": [{"text": "玄戒 O3", "kind": "product"},
                     {"text": "移动SoC", "kind": "topic"}],
    }, ensure_ascii=False), encoding="utf-8")
    profiles = load_speaker_profiles(TURNS, None)
    _, evidence = write_evidence_document(
        mdir, MINUTES, TURNS, SLIDES,
        {1: PAGE_DESC["desc"]["1"], 2: PAGE_DESC["desc"]["2"]}, profiles,
        generation={"synthetic_fixture": True})
    raw_map = {
        "meeting_summary": "合成会议依次完成开场与收束。",
        "topics": [
            {"title": "明确评审范围", "summary": "先确认合成评审目标。",
             "turn_ids": ["T000001"], "claim_ids": ["C00001"], "page_ids": ["P0001"],
             "children": [
                 {"type": "context", "title": "评审开场", "summary": "说明会议目的。",
                  "turn_ids": ["T000001"], "claim_ids": ["C00001"], "page_ids": ["P0001"]}]},
            {"title": "试点与收束", "summary": "讨论试点并收束。",
             "turn_ids": ["T000002", "T000003"], "claim_ids": ["C00002"],
             "page_ids": ["P0002"],
             "children": [
                 {"type": "decision", "title": "收束", "summary": "第二轮收束会议。",
                  "turn_ids": ["T000003"], "claim_ids": ["C00003"], "page_ids": ["P0002"]}]},
            {"title": "杂项过渡", "summary": "过渡内容。",
             "turn_ids": ["T000002"], "claim_ids": [], "page_ids": [],
             "children": []},
        ],
    }
    topic_map = meeting_topic_map._sanitize_map(
        raw_map, evidence, meeting_topic_map.current_revisions(mdir),
        model="synthetic", window_count=1, chunk_seconds=480.0)
    (mdir / "meeting.topic-map.json").write_text(
        json.dumps(topic_map, ensure_ascii=False), encoding="utf-8")
    return mdir


def make_keyword_sidecar(mdir: Path, entries: list[dict]) -> None:
    minutes = (mdir / "minutes.md").read_text(encoding="utf-8")
    revision = hashlib.sha256(minutes.encode("utf-8")).hexdigest()[:16]
    (mdir / "meeting.keywords.json").write_text(json.dumps({
        "schema": "meeting-keywords/v1", "status": "complete",
        "source_revision": revision, "facts_revision": None,
        "language": "zh-CN", "model": "synthetic", "updated_at": 1000.0,
        "keywords": entries,
    }, ensure_ascii=False), encoding="utf-8")


with tempfile.TemporaryDirectory(prefix="kb-document-test-") as tmp:
    root = Path(tmp) / "meetings"
    root.mkdir()
    full_dir = make_meeting(root, "2026-08-25_alpha")
    bare_dir = make_meeting(root, "2026-08-25_beta", full=False)
    make_keyword_sidecar(bare_dir, [{"text": "玄戒O3", "kind": "product"},
                                    {"text": "二场独有词", "kind": "topic"}])
    photo_source = Path(tmp) / "whiteboard.jpg"
    Image.new("RGB", (480, 320), (245, 240, 225)).save(photo_source)
    meeting_photos.import_photos(
        full_dir, [(photo_source, "Whiteboard.jpg")], mode="current_time",
        anchor_seconds=42.5, duration=70.0)

    doc = kb_document.kb_document(full_dir, base_url=BASE)
    slug = "2026-08-25_alpha"

    # front matter
    assert doc.startswith("---\n")
    front = doc.split("---\n", 2)[1]
    assert 'title: "Alpha 合成评审"' in front
    assert 'date: "2026-08-25"' in front
    assert 'content_type: "meeting"' in front
    assert "duration: 70.0" in front
    assert '{text: "玄戒 O3", kind: "product"}' in front
    assert '{text: "移动SoC", kind: "topic"}' in front
    assert 'source_url: "https://example.invalid/synthetic-source"' in front

    # 头部完整视频外链（有视频时不退化到音频）
    assert f"[▶ 完整视频]({BASE}/api/meetings/{slug}/media/video)" in doc
    assert "media/audio" not in doc

    # 章节顺序：总体摘要 → 关键结论 → 待办 → 议题脉络 → 屏幕内容 → 逐字稿
    order = [doc.index(f"## {name}") for name in
             ("总体摘要", "关键结论", "待办", "议题脉络", "屏幕内容", "逐字稿")]
    assert order == sorted(order), order

    # 依据保留 #mm-C 供检索，并带可点击时间深链；不残留 viewer 内部 marker/锚。
    assert "mm:evidence" not in doc and "<!--" not in doc
    assert re.search(r"先做试点仍是提议。 #mm-C\d{5}", doc)
    assert "[依据](#mm-" not in doc
    assert re.search(
        rf"#mm-C\d{{5}} \[依据 · 00:03\]\({re.escape(BASE)}/\?meeting={slug}&t=3\.5\)",
        doc)

    # 待办表：负责人/期限保留，依据编号在事项单元格内
    assert re.search(
        rf"\| 完成试点方案 #mm-C\d{{5}} \[依据 · 01:05\]"
        rf"\({re.escape(BASE)}/\?meeting={slug}&t=65\.5\) \| 王虚构 \| 下周 \| 待确认 \|",
        doc)

    # 议题脉络：标题行内嵌时间码深链
    assert re.search(rf"### \[00:00\]\({re.escape(BASE)}/\?meeting={slug}&t=0\.5\) 明确评审范围", doc)
    assert re.search(rf"### \[00:03\]\({re.escape(BASE)}/\?meeting={slug}&t=3\.5\) 试点与收束", doc)

    # 屏幕内容：时间码链接 + 图片外链 + VL 描述（`# 标题` 被抹平、think 已清洗）
    assert f"![第 1 页]({BASE}/api/meetings/{slug}/file?path=slides/page1.png)" in doc
    assert "合成页面一。蓝色测试背景。" in doc
    assert "合成推理" not in doc
    assert not re.search(r"^# 标题$", doc, re.M)

    # 现场照片独立成节，带时间深链和在线图片地址；信任边界不会把它写成决策证据。
    assert "## 现场照片" in doc
    assert f"[00:42]({BASE}/?meeting={slug}&t=42.5)" in doc
    assert (f"file?path=photos/review/F0001.jpg" in doc
            and "不独立证明会议结论" in doc)

    # 逐字稿：小数秒深链 + 说话人
    assert (f"[01:05]({BASE}/?meeting={slug}&t=65.5) **Carol：** "
            "小数秒时间码轮次，合成内容。") in doc

    # 分页详情不进入 KB 文档（与阅读版一致）
    assert "逐页过程记录" not in doc

    # base_url 覆盖生效
    other = kb_document.kb_document(full_dir, base_url="https://kb.internal:9000/")
    assert "https://kb.internal:9000/?meeting=" in other
    assert f"{BASE}/?meeting=" not in other

    # 图文 KB：HTML 自包含关键画面，不依赖截图 URL；静态解析器可回收 data URI。
    html_doc, html_stats = kb_document.kb_html_document(full_dir, base_url=BASE)
    assert 'name="meeting-kb-schema" content="meeting-kb-html/v1"' in html_doc
    assert html_doc.count("data:image/jpeg;base64,") == 3
    assert "file?path=slides/" not in html_doc
    assert "总体摘要" in html_doc and "逐字稿" in html_doc and "#mm-C" in html_doc
    assert html_stats["embedded_images"] == 2
    assert html_stats["embedded_photos"] == 1
    assert html_stats["embedded_image_bytes"] > 0
    assert html_stats["document_bytes"] == len(html_doc.encode("utf-8"))
    image_payloads = re.findall(r'data:image/jpeg;base64,([^"\s]+)', html_doc)
    assert len(image_payloads) == 3
    assert all(__import__("base64").b64decode(value).startswith(b"\xff\xd8")
               for value in image_payloads)

    # 口播/低价值画面保留文字解读但不内嵌图片，避免 KB 包体被无效帧放大。
    filtered_slides = [dict(page) for page in SLIDES]
    filtered_slides[1].update({"talking_head": True, "information_value": "low"})
    (full_dir / "slides.json").write_text(
        json.dumps(filtered_slides, ensure_ascii=False), encoding="utf-8")
    filtered_html, filtered_stats = kb_document.kb_html_document(full_dir, base_url=BASE)
    assert filtered_stats["embedded_images"] == 1
    assert filtered_html.count("data:image/jpeg;base64,") == 2
    assert "合成页面二。绿色测试背景。" in filtered_html
    (full_dir / "slides.json").write_text(
        json.dumps(SLIDES, ensure_ascii=False), encoding="utf-8")

    html_out = Path(tmp) / "single.kb.html"
    html_file_stats = kb_document.write_kb_html(full_dir, html_out, base_url=BASE)
    assert html_out.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert html_file_stats["filename"].endswith(".kb.html")
    assert "2026-08-25" in html_file_stats["filename"]

    # 缺板块降级：无媒体/无脉络/无屏幕/无 source_url，整节跳过
    bare = kb_document.kb_document(bare_dir, base_url=BASE)
    assert "## 逐字稿" in bare
    assert "▶" not in bare
    assert "## 议题脉络" not in bare and "## 屏幕内容" not in bare
    assert "source_url" not in bare
    assert '{text: "玄戒O3", kind: "product"}' in bare  # 关键字 sidecar 仍被收集
    assert "mm:evidence" not in bare

    # 英文纪要：文档语言跟随主语言
    en_dir = root / "2026-08-25_gamma"
    en_dir.mkdir()
    en_turns = [{"speaker": "Dana", "voice": "v_8004", "start": 0.0, "end": 4.0,
                 "text": "Synthetic opening statement."}]
    en_minutes = """# Meeting Minutes

## Overall Summary

- **Main point**: Synthetic review, no real content. <!-- mm:evidence kind=purpose status=informational confidence=high turns=T000001 -->
- **Key Conclusions**:
  1. Pilot remains a proposal. <!-- mm:evidence kind=alignment status=proposal confidence=high turns=T000001 -->
"""
    (en_dir / "transcript.spk.json").write_text(
        json.dumps(en_turns, ensure_ascii=False), encoding="utf-8")
    (en_dir / "minutes.md").write_text(en_minutes, encoding="utf-8")
    en_doc = kb_document.kb_document(en_dir, base_url=BASE)
    assert "## Overall Summary" in en_doc and "## Key Conclusions" in en_doc
    assert "## Transcript" in en_doc
    assert f"[00:00]({BASE}/?meeting=2026-08-25_gamma&t=0) **Dana:**" in en_doc
    assert re.search(r"Pilot remains a proposal\. #mm-C\d{5}", en_doc)

    # 单场 kbpack：只有 kb.md + manifest
    out1 = Path(tmp) / "single.kbpack.zip"
    stats1 = kb_document.build_kb_pack([(slug, full_dir, "Alpha 合成评审", "2026-08-25")],
                                       out1, base_url=BASE)
    with zipfile.ZipFile(out1) as archive:
        assert set(archive.namelist()) == {f"{slug}.kb.md", "manifest.json"}
        manifest1 = json.loads(archive.read("manifest.json"))
        assert archive.read(f"{slug}.kb.md").decode("utf-8") == doc
    assert manifest1["schema"] == "kb-pack/v1"
    assert manifest1["base_url"] == BASE
    assert manifest1["generator"]["version"]
    entry1 = manifest1["documents"][0]
    assert entry1["file"] == f"{slug}.kb.md" and entry1["sha256"]
    assert entry1["keywords"] == ["玄戒 O3", "移动SoC"]
    tag = next(t for t in manifest1["tags"] if t["text"] == "玄戒 O3")
    assert tag["slugs"] == [slug] and tag["kinds"] == ["product"]
    assert stats1["filename"].endswith(".kbpack.zip")
    assert "2026-08-25" in stats1["filename"]
    # 体积极小：纯文本包远小于 1MB
    assert stats1["bytes"] < 100_000

    # 多场 kbpack：每场一份 kb.md + 文字版 index.md，贯穿关键字共享归组
    out2 = Path(tmp) / "multi.kbpack.zip"
    stats2 = kb_document.build_kb_pack(
        [(slug, full_dir, "Alpha 合成评审", "2026-08-25"),
         ("2026-08-25_beta", bare_dir, None, None)],
        out2, base_url=BASE)
    with zipfile.ZipFile(out2) as archive:
        names = set(archive.namelist())
        assert names == {f"{slug}.kb.md", "2026-08-25_beta.kb.md",
                         "index.md", "manifest.json"}
        index_md = archive.read("index.md").decode("utf-8")
        manifest2 = json.loads(archive.read("manifest.json"))
    assert "内容清单" in index_md and "贯穿关键字" in index_md
    assert re.search(r"玄戒 ?O3（product）→ 2026-08-25_alpha、2026-08-25_beta", index_md)
    assert "二场独有词" not in index_md  # 独有词不是贯穿线索
    assert manifest2["counts"]["documents"] == 2
    assert manifest2["counts"]["shared_keywords"] == 1
    assert stats2["name"] == "玄戒 O3"  # 默认名取最高频共享关键字
    beta_doc = manifest2["documents"][1]
    assert beta_doc["title"] == "beta"  # 无 meta/显式标题时回退 slug 派生名
    assert beta_doc["date"] == "2026-08-25"

    # 多内容图文 KB 仍使用 kbpack 容器，但每场文档均可单独上传。
    out3 = Path(tmp) / "multi-html.kbpack.zip"
    stats3 = kb_document.build_kb_pack(
        [(slug, full_dir, "Alpha 合成评审", "2026-08-25"),
         ("2026-08-25_beta", bare_dir, None, None)],
        out3, base_url=BASE, document_format="html")
    with zipfile.ZipFile(out3) as archive:
        names3 = set(archive.namelist())
        manifest3 = json.loads(archive.read("manifest.json"))
        full_html = archive.read(f"{slug}.kb.html").decode("utf-8")
    assert names3 == {f"{slug}.kb.html", "2026-08-25_beta.kb.html",
                      "index.md", "manifest.json"}
    assert manifest3["document_format"] == "html"
    assert manifest3["image_mode"] == "embedded_base64"
    assert manifest3["counts"]["embedded_images"] == 2
    assert "data:image/jpeg;base64," in full_html
    assert stats3["documents"] == 2

    # 默认 base：无参数时回退 env/loopback 常量
    default_doc = kb_document.kb_document(full_dir, base_url=kb_document.default_base_url())
    assert "http://127.0.0.1:8899/?meeting=" in default_doc

    # 空目录拒绝导出
    empty_dir = root / "2026-08-25_empty"
    empty_dir.mkdir()
    try:
        kb_document.kb_document(empty_dir, base_url=BASE)
    except ValueError:
        pass
    else:
        raise AssertionError("空会议目录应抛 ValueError")

print("kb document: front-matter/deep-links/degradation/pack passed")
