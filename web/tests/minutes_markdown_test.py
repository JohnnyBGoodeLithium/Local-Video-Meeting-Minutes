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
    strip_visible_evidence_ids,
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

# marker 独占状态列（真实 PLM 纪要形态）：剥离后只剩 3 个非空单元格，
# 负责人/期限仍须正确拆出，状态由 claim_status 兜底，事项里不得残留竖线。
marker_status_minutes = """# 会议纪要

## 总体摘要

### 待办事项

| 事项 | 负责人 | 期限 | 状态 |
| --- | --- | --- | --- |
| 合成事项甲 | Alex Example | 周五 | <!-- mm:evidence kind=action status=confirmed confidence=high turns=T000001 --> |
"""
with tempfile.TemporaryDirectory(prefix="minutes-marker-status-test-") as tmp:
    mdir = Path(tmp) / "synthetic"
    mdir.mkdir()
    turns = [{"speaker": "Alex Example", "voice": "v_test", "start": 1, "end": 2,
              "text": "请在周五前完成合成事项甲。"}]
    (mdir / "transcript.spk.json").write_text(
        json.dumps(turns, ensure_ascii=False), encoding="utf-8")
    evidence = build_evidence_document(mdir, marker_status_minutes, turns, [], {}, [])
    assert len(evidence["actions"]) == 1
    action = evidence["actions"][0]
    assert action["text"] == "合成事项甲"
    assert action["owner"] == "Alex Example"
    assert action["deadline"] == "周五"
    reading = minutes_reading_markdown(marker_status_minutes, evidence)
    row = next(line for line in reading.splitlines() if "合成事项甲" in line)
    assert "| 合成事项甲 [依据](#mm-C00001) | Alex Example | 周五 | 已确认 |" == row

# 旧 sidecar：claim["action"] 已按旧逻辑存成误判结果，读路径须用 claim 原文重拆。
stale_claim = {
    "id": "C00001", "kind": "action", "status": "confirmed", "confidence": "high",
    "section": "待办事项",
    "text": "| 合成事项甲 | Alex Example | 周五 |",
    "action": {"text": "| 合成事项甲 | Alex Example | 周五 |",
               "owner": None, "deadline": None, "status": None},
    "turn_ids": ["T000001"], "page_ids": [], "evidence_ids": ["T000001"],
}
from meeting_artifact import action_items_from_claims  # noqa: E402
stale_actions = action_items_from_claims([stale_claim])
assert stale_actions[0]["text"] == "合成事项甲"
assert stale_actions[0]["owner"] == "Alex Example"
assert stale_actions[0]["deadline"] == "周五"

# 旧 action 字段虽然非空，却已经发生“整行塞进 text + 字段右移复制”；读取时自愈。
shifted_claim = {
    **stale_claim,
    "action": {"text": "合成事项乙 | Blair Example | 待确认",
               "owner": "合成事项乙", "deadline": "Blair Example", "status": "待确认"},
}
shifted = action_items_from_claims([shifted_claim])[0]
assert shifted["text"] == "合成事项乙"
assert shifted["owner"] == "Blair Example"
assert shifted["deadline"] == "待确认"
assert shifted["status"] == "待确认"

print("Minutes Markdown: marker-in-status-cell action rows passed")

# 模型把 marker 包在反引号里：替换成“依据”链接时必须拆掉反引号，
# 否则 markdown-it 渲染成行内代码，前端拿不到 a[href^="#mm-"]。
from meeting_artifact import markdown_with_evidence_links  # noqa: E402
backtick_minutes = (
    "- 合成结论。`<!-- mm:evidence kind=discussion status=confirmed confidence=high turns=T000001 -->`\n"
    "- 无标记普通行。\n"
)
backtick_evidence = {"claims": [{
    "id": "C00001",
    "marker": "<!-- mm:evidence kind=discussion status=confirmed confidence=high turns=T000001 -->",
}]}
linked = markdown_with_evidence_links(backtick_minutes, backtick_evidence)
assert "`" not in linked
assert "[依据](#mm-C00001)" in linked
linked_html = MarkdownIt("default", {"html": False}).render(linked)
assert '<a href="#mm-C00001">依据</a>' in linked_html
assert "<code>" not in linked_html
# 未包裹反引号的旧形态保持兼容
plain = markdown_with_evidence_links(
    "- 合成结论。 <!-- mm:evidence kind=discussion status=confirmed confidence=high turns=T000001 -->\n",
    backtick_evidence)
assert "[依据](#mm-C00001)" in plain

print("Minutes Markdown: backtick-wrapped evidence markers passed")

# T ID 是机器侧证据主键，不是员工身份；人读正文只保留依据 chip，括号尾注不应外露。
visible_ids = "- 合成结论。（T000001, T000002） <!-- mm:evidence kind=decision status=confirmed confidence=high turns=T000001,T000002 -->"
clean_visible = strip_visible_evidence_ids(visible_ids)
assert "（T000001" not in clean_visible and "mm:evidence" in clean_visible
with tempfile.TemporaryDirectory(prefix="minutes-visible-id-test-") as tmp:
    mdir = Path(tmp) / "synthetic"
    mdir.mkdir()
    turns = [
        {"speaker": "Alex Example", "start": 1, "end": 2, "text": "合成结论一。"},
        {"speaker": "Bo Example", "start": 3, "end": 4, "text": "合成结论二。"},
    ]
    (mdir / "transcript.spk.json").write_text(json.dumps(turns), encoding="utf-8")
    evidence = build_evidence_document(mdir, visible_ids, turns, [], {}, [])
    assert evidence["claims"][0]["text"] == "合成结论。"
    projected_ids = minutes_reading_markdown(visible_ids, evidence)
    assert "（T000001" not in projected_ids and "turns=T000001,T000002" in projected_ids

print("Minutes Markdown: machine turn IDs hidden from reading projection")
