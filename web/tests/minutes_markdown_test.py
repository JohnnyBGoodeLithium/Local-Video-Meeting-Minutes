#!/usr/bin/env python3
"""验证旧待办表格修复与结构化 action 投影（全虚构数据）。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from markdown_it import MarkdownIt


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
from meeting_artifact import build_evidence_document, normalize_minutes_markdown  # noqa: E402


minutes = """# 会议纪要

## 总体摘要

- **待办事项**：
| 事项 | 负责人 | 期限 | 状态 |
| --- | --- | --- | --- |
| 完成合成验证 <!-- mm:evidence kind=action status=open confidence=high turns=T000001 --> | Alex Example | 周五 | 进行中 |
"""

normalized = normalize_minutes_markdown(minutes)
tokens = MarkdownIt("default", {"html": False}).parse(normalized)
assert sum(token.type == "table_open" for token in tokens) == 1
assert normalize_minutes_markdown(normalized) == normalized

with tempfile.TemporaryDirectory(prefix="minutes-markdown-test-") as tmp:
    mdir = Path(tmp) / "synthetic"
    mdir.mkdir()
    turns = [{"speaker": "Alex Example", "voice": "v_test", "start": 1, "end": 2,
              "text": "请在周五前完成合成验证。"}]
    (mdir / "transcript.spk.json").write_text(
        json.dumps(turns, ensure_ascii=False), encoding="utf-8")
    evidence = build_evidence_document(mdir, minutes, turns, [], {}, [])
    assert len(evidence["actions"]) == 1
    action = evidence["actions"][0]
    assert action["text"] == "完成合成验证"
    assert action["owner"] == "Alex Example"
    assert action["deadline"] == "周五"
    assert action["status"] == "进行中"
    assert action["claim_id"] == "C00001"
    assert action["turn_ids"] == ["T000001"]

fullwidth = "｜事项｜负责人｜\n｜---｜---｜\n｜合成事项｜待确认｜\n"
assert sum(token.type == "table_open" for token in MarkdownIt("default").parse(
    normalize_minutes_markdown(fullwidth))) == 1

print("Minutes Markdown: legacy tables and structured actions passed")
