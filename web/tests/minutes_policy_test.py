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
    mb.ensure_vl_server = lambda: ("synthetic://vl", None)
    mb.describe_pages = lambda *_args, **_kwargs: {
        1: "## 标题\n试点方案页。",
        2: "## 标题\n预算参考页，没有对应讨论。",
    }
    out, stats = mb.generate(mdir, vl=True)
    evidence = json.loads((mdir / "minutes.evidence.json").read_text(encoding="utf-8"))
    minutes = out.read_text(encoding="utf-8")

    assert stats["claims"] == 4
    assert evidence["policy"]["seniority_rule"].startswith("职级最多影响")
    assert evidence["claims"][1]["status"] == "proposal"
    assert evidence["sources"]["pages"][1]["display_status"] == "display_only"
    assert "页面 P0002 · 第2页 · 仅展示" in minutes
    assert all("meeting-minutes-prompt/v1" in p for p in seen_prompts)
    assert all("speaker_profiles" in p and "T000001" in p for p in seen_prompts)
    assert any("P0001" in p and "org_depth" in p for p in seen_prompts)

print("Minutes policy/evidence: synthetic fixture passed")
