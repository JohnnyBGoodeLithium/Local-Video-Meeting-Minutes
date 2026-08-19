#!/usr/bin/env python3
"""用全虚构输入验证结构化 Prompt、职级规则、证据 marker 与页面分层。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
import minutes_by_page as mb  # noqa: E402


with tempfile.TemporaryDirectory(prefix="minutes-policy-") as tmp:
    mdir = Path(tmp) / "meetings" / "synthetic"
    (mdir / "slides").mkdir(parents=True)
    turns = [
        {"speaker": "Synthetic Director", "voice": "v_test", "start": 1.0, "end": 3.0,
         "text": "我建议先做试点，最终决定下周再确认。"},
    ]
    pages = [
        {"kind": "slide", "page": 1, "first": 0.0, "image": "one.png", "ranges": [[0, 5]]},
        {"kind": "slide", "page": 2, "first": 5.0, "image": "two.png", "ranges": [[5, 10]]},
    ]
    (mdir / "transcript.spk.json").write_text(json.dumps(turns, ensure_ascii=False), encoding="utf-8")
    (mdir / "slides.json").write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    (mdir / "slides" / "one.png").write_bytes(b"synthetic-one")
    (mdir / "slides" / "two.png").write_bytes(b"synthetic-two")

    seen_prompts = []

    def fake_chat(prompt, max_tokens=8192, model=mb.MODEL):
        seen_prompts.append(prompt)
        if "只包含若干页面" in prompt:
            return ("### 第1页 [00:00] 试点建议\n"
                    "- [00:01] 发言者建议先做试点，最终决定尚未形成。 "
                    "<!-- mm:evidence kind=discussion status=proposal confidence=high "
                    "turns=T000001 pages=P0001 -->\n"
                    "- **本页结论**：该内容是提议，不是已确认结论。 "
                    "<!-- mm:evidence kind=alignment status=proposal confidence=high "
                    "turns=T000001 pages=P0001 -->", {"completion_tokens": 100})
        return ("## 总体摘要\n"
                "- **主旨**：讨论一个待确认的试点建议。 "
                "<!-- mm:evidence kind=purpose status=informational confidence=high "
                "turns=T000001 pages=P0001 -->\n"
                "- **关键结论**：未形成已确认结论。\n\n"
                "## 议题板块\n"
                "- 试点讨论（第1页，00:00 起）：提出建议，待下周确认。 "
                "<!-- mm:evidence kind=discussion status=proposal confidence=high "
                "turns=T000001 pages=P0001 -->", {"completion_tokens": 100})

    mb.chat = fake_chat
    from meeting_core.llm import Completion  # noqa: E402

    overview_calls = 0

    def fake_overview_direct(prompt, notes):
        global overview_calls
        seen_prompts.append(prompt)
        overview_calls += 1
        if overview_calls == 1:
            # 再模拟文本生成期间发生一次身份修正；第一次结果必须被丢弃，
            # 第二次只复用已有 VL 结果，不重复视觉推理。
            final_turn = [{**turns[0], "speaker": "Final Synthetic Owner"}]
            (mdir / "transcript.spk.json").write_text(
                json.dumps(final_turn, ensure_ascii=False), encoding="utf-8")
        return Completion(
            content=("## 总体摘要\n"
                     "- **主旨**：讨论一个待确认的试点建议。 "
                     "<!-- mm:evidence kind=purpose status=informational confidence=high "
                     "turns=T000001 pages=P0001 -->\n"
                     "- **关键结论**：未形成已确认结论。\n\n"
                     "## 议题板块\n"
                     "- 试点讨论（第1页，00:00 起）：提出建议，待下周确认。 "
                     "<!-- mm:evidence kind=discussion status=proposal confidence=high "
                     "turns=T000001 pages=P0001 -->"),
            usage={"completion_tokens": 100}, elapsed=0.01)

    mb.overview_direct = fake_overview_direct
    mb.ensure_vl_server = lambda: ("synthetic://vl", None)
    describe_calls = 0

    def fake_describe_pages(*_args, **_kwargs):
        global describe_calls
        describe_calls += 1
        # 模拟耗时 VL 期间用户修正说话人：终稿必须在 VL 后重读身份，
        # 不能继续使用 generate() 入口处的旧内存副本。
        if describe_calls == 1:
            corrected = [{**turns[0], "speaker": "Corrected Synthetic Owner"}]
            (mdir / "transcript.spk.json").write_text(
                json.dumps(corrected, ensure_ascii=False), encoding="utf-8")
        descriptions = {
            1: "## 标题\n试点方案页。",
            2: "## 标题\n预算参考页，没有对应讨论。",
        }
        (mdir / "page_desc.json").write_text(
            json.dumps({"desc": descriptions}, ensure_ascii=False), encoding="utf-8")
        return descriptions

    mb.describe_pages = fake_describe_pages
    out, stats = mb.generate(mdir, vl=True)
    evidence = json.loads((mdir / "minutes.evidence.json").read_text(encoding="utf-8"))
    minutes = out.read_text(encoding="utf-8")

    assert stats["claims"] == 4
    assert evidence["policy"]["seniority_rule"].startswith("职级最多影响")
    assert evidence["sources"]["transcript"][0]["speaker"] == "Final Synthetic Owner"
    assert evidence["claims"][1]["status"] == "proposal"
    assert evidence["sources"]["pages"][1]["display_status"] == "display_only"
    assert "页面 P0002 · 第2页 · 仅展示" in minutes
    assert all("meeting-minutes-prompt/v1" in p for p in seen_prompts)
    assert all("speaker_profiles" in p and "T000001" in p for p in seen_prompts)
    assert any("P0001" in p and "org_depth" in p for p in seen_prompts)
    assert all("Synthetic Director" not in p for p in seen_prompts)
    assert any("Corrected Synthetic Owner" in p for p in seen_prompts)
    assert any("Final Synthetic Owner" in p for p in seen_prompts)
    assert overview_calls == 2 and describe_calls == 1

print("Minutes policy/evidence: synthetic fixture passed")
