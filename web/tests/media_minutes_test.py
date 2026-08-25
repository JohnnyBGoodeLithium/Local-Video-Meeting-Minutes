#!/usr/bin/env python3
"""媒体版纪要 prompt：content_type=media 走论证结构、不生成待办（全虚构数据）。

覆盖：profile 选择总开关、shot 页媒体 VL prompt 选择、媒体章节结构落盘、
阅读投影/章节结构/画面价值分级的媒体口径，以及会议口径一字不变的回归。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))

import meeting_structure  # noqa: E402
import minutes_by_page as mb  # noqa: E402
from meeting_artifact import minutes_reading_markdown  # noqa: E402
from meeting_core.llm import Completion  # noqa: E402
from meeting_core.minutes_overview import (  # noqa: E402
    MEDIA_REQUIRED, generate_direct, generate as overview_generate)


# ---- 1. profile 总开关：meta.json content_type 分流，异常一律会议 ----------
with tempfile.TemporaryDirectory(prefix="media-profile-") as temp:
    mdir = Path(temp)
    assert mb.minutes_profile(mdir).kind == "meeting"          # 无 meta.json
    (mdir / "meta.json").write_text(json.dumps({"content_type": "media"}), encoding="utf-8")
    assert mb.minutes_profile(mdir).kind == "media"
    (mdir / "meta.json").write_text(json.dumps({"content_type": "unknown"}), encoding="utf-8")
    assert mb.minutes_profile(mdir).kind == "meeting"          # 未知值回退
    (mdir / "meta.json").write_text("{broken", encoding="utf-8")
    assert mb.minutes_profile(mdir).kind == "meeting"          # 坏文件回退

# ---- 2. shot 页 VL prompt 选择 ----------------------------------------------
shot_detail, shot_compact, shot_label = mb.vl_prompts({"shot": True})
assert "论证角色" in shot_detail and "证据帧" in shot_detail
assert "镜头类型" in shot_compact and shot_label == "镜头类型"
meet_detail, meet_compact, meet_label = mb.vl_prompts({})
assert "会议中共享屏幕" in meet_detail and "页面角色" in meet_detail
assert meet_label == "页面类型"


# ---- 3. describe_pages 对 shot 页发媒体 prompt ------------------------------
class FakeModelsResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"data": [{"id": "synthetic-vl"}]}).encode("utf-8")


with tempfile.TemporaryDirectory(prefix="media-vl-prompt-") as temp:
    mdir = Path(temp)
    (mdir / "slides").mkdir()
    (mdir / "slides" / "shot.jpg").write_bytes(b"synthetic-shot")
    (mdir / "slides" / "page.jpg").write_bytes(b"synthetic-page")
    pages = [
        {"page": 1, "image": "shot.jpg", "first": 0, "shot": True},
        {"page": 2, "image": "page.jpg", "first": 10},
    ]
    sent = {}

    def fake_vl_chat(_api, _model, image, _max_tokens, prompt):
        sent[image.name] = prompt
        return "## 标题\n合成画面", {"completion_tokens": 5}

    original_urlopen = mb.urllib.request.urlopen
    original_vl_chat = mb.chat_with_image
    try:
        mb.urllib.request.urlopen = lambda *_args, **_kwargs: FakeModelsResponse()
        mb.chat_with_image = fake_vl_chat
        mb.describe_pages(mdir, pages, "http://synthetic/v1")
    finally:
        mb.urllib.request.urlopen = original_urlopen
        mb.chat_with_image = original_vl_chat
    assert "论证角色" in sent["shot.jpg"] and "镜头" in sent["shot.jpg"]
    assert "会议中共享屏幕" in sent["page.jpg"] and "页面角色" in sent["page.jpg"]


# ---- 4. generate() 媒体口径端到端（mock 文本模型）---------------------------
MEDIA_OVERVIEW = (
    "## 总体摘要\n"
    "- **主旨**：合成视频主旨。 "
    "<!-- mm:evidence kind=purpose status=informational confidence=high turns=T000001 -->\n"
    "- **核心观点**：\n"
    "- 明确主张：合成观点一。 "
    "<!-- mm:evidence kind=discussion status=informational confidence=high "
    "turns=T000002 pages=P0001 -->\n\n"
    "## 规格与参数\n"
    "- 合成参数 8GB（引用官方）。 "
    "<!-- mm:evidence kind=discussion status=informational confidence=high turns=T000002 -->\n\n"
    "## 论证脉络\n"
    "- 铺垫与开箱（第1页，00:00 起）：合成铺垫。 "
    "<!-- mm:evidence kind=discussion status=informational confidence=high "
    "turns=T000001 pages=P0001 -->\n"
    "- 实测与结论（第2页，00:05 起）：合成结论。 "
    "<!-- mm:evidence kind=discussion status=informational confidence=high "
    "turns=T000003 pages=P0002 -->\n\n"
    "### 值得注意的质疑/保留意见\n"
    "- 合成保留意见。 "
    "<!-- mm:evidence kind=discussion status=open confidence=medium turns=T000003 -->\n")

MEDIA_BLOCK = (
    "### 第1页 [00:00] 合成镜头一\n"
    "- [00:01] 作者展示合成规格表。 "
    "<!-- mm:evidence kind=discussion status=informational confidence=high "
    "turns=T000001 pages=P0001 -->\n"
    "- **论证角色**：给出证据——规格表支撑核心观点。 "
    "<!-- mm:evidence kind=discussion status=informational confidence=high "
    "turns=T000001 pages=P0001 -->")

MEETING_OVERVIEW = (
    "## 总体摘要\n"
    "- **主旨**：合成会议。 "
    "<!-- mm:evidence kind=purpose status=informational confidence=high turns=T000001 -->\n"
    "- **关键结论**：未形成已确认结论。\n\n"
    "### 待办事项\n\n未形成明确待办\n\n"
    "### 风险/待确认\n- 无\n\n"
    "## 议题板块\n"
    "- 合成议题（第1页，00:00 起）：合成讨论。 "
    "<!-- mm:evidence kind=discussion status=informational confidence=high "
    "turns=T000001 pages=P0001 -->")

MEETING_BLOCK = (
    "### 第1页 [00:00] 合成议题\n"
    "- [00:01] 合成讨论要点。 "
    "<!-- mm:evidence kind=discussion status=informational confidence=high "
    "turns=T000001 pages=P0001 -->\n"
    "- **本页结论**：未形成结论")

MEDIA_DESCS = {
    1: ("## 标题\n合成规格表\n## 论证角色\nevidence\n"
        "## 信息价值\nhigh：合成规格表承载核心论点。\n"
        "## 页面内容\n- 合成参数 8GB"),
    2: ("## 标题\n合成场景\n## 论证角色\ncontext\n"
        "## 页面内容\n- 合成场景空镜，主讲人特写"),
}


def make_fixture(root: Path, *, media: bool) -> Path:
    mdir = root / "meetings" / "synthetic-media" if media else root / "meetings" / "synthetic-meeting"
    (mdir / "slides").mkdir(parents=True)
    if media:
        (mdir / "meta.json").write_text(
            json.dumps({"content_type": "media"}), encoding="utf-8")
    turns = [
        {"speaker": "Synthetic Author", "start": 0.0, "end": 2.0, "text": "合成开场铺垫。"},
        {"speaker": "Synthetic Author", "start": 2.0, "end": 5.0, "text": "合成规格与观点。"},
        {"speaker": "Synthetic Author", "start": 5.0, "end": 9.0, "text": "合成结论与保留。"},
    ]
    pages = [
        {"kind": "slide", "page": 1, "first": 0.0, "image": "one.jpg",
         "captured": 1.0, "ranges": [[0.0, 5.0]], "shot": media},
        {"kind": "slide", "page": 2, "first": 5.0, "image": "two.jpg",
         "captured": 6.0, "ranges": [[5.0, 9.0]], "shot": media},
    ]
    if not media:
        for page in pages:
            page.pop("shot")
    (mdir / "transcript.spk.json").write_text(
        json.dumps(turns, ensure_ascii=False), encoding="utf-8")
    (mdir / "slides.json").write_text(
        json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    return mdir


def run_generate(mdir: Path, *, media: bool):
    seen = {}

    def fake_chat(prompt, max_tokens=8192, model=mb.MODEL):
        seen.setdefault("group", []).append(prompt)
        return (MEDIA_BLOCK if media else MEETING_BLOCK), {"completion_tokens": 50}

    def fake_overview_direct(prompt, notes, profile=None):
        seen["summary_prompt"] = prompt
        seen["profile_kind"] = profile.kind if profile else None
        return Completion(content=MEDIA_OVERVIEW if media else MEETING_OVERVIEW,
                          usage={"completion_tokens": 100}, elapsed=0.01)

    original = (mb.chat, mb.overview_direct, mb.ensure_vl_server, mb.describe_pages)
    mb.chat = fake_chat
    mb.overview_direct = fake_overview_direct
    mb.ensure_vl_server = lambda: ("synthetic://vl", None)
    mb.describe_pages = lambda *_args, **_kwargs: dict(MEDIA_DESCS)
    try:
        out, stats = mb.generate(mdir, vl=True)
    finally:
        (mb.chat, mb.overview_direct, mb.ensure_vl_server, mb.describe_pages) = original
    return out, stats, seen


with tempfile.TemporaryDirectory(prefix="media-minutes-") as temp:
    mdir = make_fixture(Path(temp), media=True)
    out, stats, seen = run_generate(mdir, media=True)
    md = out.read_text(encoding="utf-8")

    assert seen["profile_kind"] == "media"
    summary_prompt = seen["summary_prompt"]
    assert "公开视频" in summary_prompt and "论证脉络" in summary_prompt
    assert "绝不生成待办事项" in summary_prompt              # 来自媒体证据规则
    assert "| 事项 | 负责人 |" not in summary_prompt          # 不带会议待办表结构
    assert "结论策略配置" not in summary_prompt               # 会议结论策略不进媒体 prompt
    assert any("论证角色" in p for p in seen["group"])       # 逐镜头块 prompt

    assert md.startswith("# 视频分析纪要")
    for heading in ("## 总体摘要", "## 规格与参数", "## 论证脉络",
                    "### 值得注意的质疑/保留意见", "## 分镜头详情", "## 附录: 镜头详解"):
        assert heading in md, heading
    assert "待办事项" not in md and "kind=action" not in md
    assert "有讲解" in md                                     # 两个镜头页都有逐字稿

    evidence = json.loads((mdir / "minutes.evidence.json").read_text(encoding="utf-8"))
    assert evidence["generation"]["content_type"] == "media"
    assert len(evidence["claims"]) == 8                      # 全部 marker 成 claim
    assert all(claim["kind"] != "action" for claim in evidence["claims"])

    # 阅读投影：媒体纪要同样只保留逐镜头详情之前的常规部分
    reading = minutes_reading_markdown(md, evidence)
    assert "## 论证脉络" in reading and "## 分镜头详情" not in reading
    assert "镜头详解" not in reading

    # 章节结构：无“议题板块”时按画面片段降级；媒体论证角色驱动价值分级
    turns = json.loads((mdir / "transcript.spk.json").read_text(encoding="utf-8"))
    timeline = json.loads((mdir / "slides.json").read_text(encoding="utf-8"))
    structure = meeting_structure.build_structure(
        md, turns, timeline, MEDIA_DESCS, evidence, duration=9.0)
    assert structure["chapter_source"] == "visual_segments"
    visuals = {v["page"]: v for v in structure["visuals"] if v["kind"] == "slide"}
    assert visuals[1]["content_role"] == "evidence"
    assert visuals[1]["information_value"] == "high"
    assert visuals[1]["value_source"] == "vl"
    assert visuals[2]["content_role"] == "context"
    assert visuals[2]["information_value"] == "low"          # 铺垫帧启发式降级
    assert visuals[2]["value_source"] == "heuristic"
    assert "铺垫" in visuals[2]["value_reason"]
    assert "论证角色" not in visuals[1]["display_description"]  # badge 元数据不进正文

    # ---- 回归：同一 fixtures 去掉 meta.json → 会议口径一字不变 ---------------
with tempfile.TemporaryDirectory(prefix="meeting-control-") as temp:
    mdir = make_fixture(Path(temp), media=False)
    out, stats, seen = run_generate(mdir, media=False)
    md = out.read_text(encoding="utf-8")
    assert seen["profile_kind"] == "meeting"
    assert "| 事项 | 负责人 |" in seen["summary_prompt"]       # 会议待办表结构保留
    assert "结论策略配置" in seen["summary_prompt"]
    assert any("本页结论" in p for p in seen["group"])
    assert md.startswith("# 会议纪要")
    assert "## 分页详情" in md and "### 待办事项" in md
    evidence = json.loads((mdir / "minutes.evidence.json").read_text(encoding="utf-8"))
    assert evidence["generation"]["content_type"] == "meeting"


# ---- 5. overview 直出护栏：媒体必需章节，不触发待办定点修复 ------------------
class SequenceClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def complete(self, prompt, **kwargs):
        self.calls.append(prompt)
        return Completion(content=self.outputs.pop(0), usage={}, elapsed=0.01)


MEDIA_DIRECT_OK = (
    "## 总体摘要\n- **主旨**：合成。\n- **核心观点**：合成观点。\n\n"
    "## 规格与参数\n- 未提及具体规格参数\n\n"
    "## 论证脉络\n- 合成环节（第1页，00:00 起）：合成。\n\n"
    "### 值得注意的质疑/保留意见\n- 作者未提出明显保留")
client = SequenceClient([MEDIA_DIRECT_OK])
result = generate_direct("合成媒体 prompt", "合成媒体证据规则", notes="合成上下文",
                         client=client, required=MEDIA_REQUIRED, validator=None)
assert result.content == MEDIA_DIRECT_OK and len(client.calls) == 1
assert not any("待办章节" in prompt for prompt in client.calls)   # 无待办修复轮

# 媒体 map/reduce：分片/合并走媒体 prompt，无待办合规校验与修复
class MediaMapReduceClient:
    def __init__(self):
        self.kinds = []

    def complete(self, prompt, **kwargs):
        if "连续时间片段" in prompt and "论证环节" in prompt:
            self.kinds.append("map")
            return Completion(content="- 合成笔记 T000001", usage={}, elapsed=0.01)
        assert "待办章节" not in prompt
        self.kinds.append("reduce")
        return Completion(content=MEDIA_DIRECT_OK, usage={}, elapsed=0.01)


context = {"schema": "meeting-minutes-prompt/v1", "speaker_profiles": [],
           "pages": [{"id": "P0001", "number": 1}],
           "turns": [{"id": "T000001", "index": 0, "start": 0.0, "end": 4.0,
                      "speaker": "合成作者", "voice_id": None, "person_id": None,
                      "page_id": "P0001", "text": "合成内容。"}]}
mc = MediaMapReduceClient()
overview = overview_generate(context, {"version": "synthetic/v1"}, "合成媒体证据规则",
                             client=mc, kind="media")
assert mc.kinds == ["map", "reduce"]
assert "## 论证脉络" in overview.content and "待办事项" not in overview.content

print("Media minutes: profile 分流 / 媒体章节结构 / VL 媒体 prompt / 护栏与会议回归全部通过")
