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
from meeting_artifact import (  # noqa: E402
    action_candidates_from_minutes,
    build_evidence_document,
    minutes_reading_markdown,
    normalize_minutes_markdown,
)


minutes = """# 会议纪要

## 总体摘要

### 待办事项

| 事项 | 负责人 | 期限 | 状态 |
| --- | --- | --- | --- |
| 完成合成验证 <!-- mm:evidence kind=action status=open confidence=high turns=T000001 --> | Alex Example | 周五 | 进行中 |

## 分页详情

### 第1页 [00:01] 合成开场

- 确认音频连接正常。 <!-- mm:evidence kind=action status=informational confidence=high turns=T000001 -->
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
    false_action = next(claim for claim in evidence["claims"] if claim["id"] == "C00002")
    assert false_action["kind"] == "action" and false_action["formal_action"] is False
    assert evidence["linkage"]["formal_action_count"] == 1
    assert evidence["linkage"]["nonformal_action_claim_count"] == 1

fullwidth = "｜事项｜负责人｜\n｜---｜---｜\n｜合成事项｜待确认｜\n"
assert sum(token.type == "table_open" for token in MarkdownIt("default").parse(
    normalize_minutes_markdown(fullwidth))) == 1

reading_source = """# 会议纪要

## 总体摘要

- 常规结论。

## 议题板块

- 合成议题（第1页，00:00 起）：合成摘要。

## 分页详情

### 第1页 [00:00] 不应出现在阅读版

- 技术性逐页事实。
"""
reading = minutes_reading_markdown(reading_source)
assert "常规结论" in reading and "议题板块" in reading
assert "分页详情" not in reading and "技术性逐页事实" not in reading
assert minutes_reading_markdown(reading) == reading

ungrounded = """# 会议纪要

## 总体摘要

### 待办事项

| 事项 | 负责人 | 期限 | 状态 |
| --- | --- | --- | --- |
| 没有依据的模型建议 | 某人 | 明天 | 已确认 |

### 风险/待确认

- 合成风险。

## 议题板块

没有列表符号的模型议题（第1页，00:00 起）：不应重复进入常规纪要。
"""
grounded_evidence = {"actions": [{
    "claim_id": "C00009", "text": "完成合成验证", "owner": "Alex Example",
    "deadline": "周五", "status": "进行中", "claim_status": "confirmed",
    "turn_ids": ["T000001"], "page_ids": [],
}]}
projected = minutes_reading_markdown(
    ungrounded, grounded_evidence, include_topic_section=False)
assert "没有依据的模型建议" not in projected
assert "完成合成验证 [依据](#mm-C00009)" in projected
assert "## 议题板块" not in projected and "### 风险/待确认" in projected
candidates = action_candidates_from_minutes(ungrounded, grounded_evidence["actions"])
assert len(candidates) == 1 and candidates[0]["text"] == "没有依据的模型建议"
assert candidates[0]["verification_state"] == "unlinked"

print("Minutes Markdown: legacy tables and structured actions passed")
