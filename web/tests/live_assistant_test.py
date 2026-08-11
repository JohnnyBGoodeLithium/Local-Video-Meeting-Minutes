#!/usr/bin/env python3
"""用纯虚构内容验证真实本地 LLM 的问答与结构化修改协议。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "web"))
import assistant_service as assistant  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="meeting-assistant-live-") as tmp:
        root = Path(tmp)
        transcript = root / "transcript.spk.json"
        minutes = root / "minutes.md"
        transcript.write_text(json.dumps([
            {"speaker": "测试甲", "voice": None, "start": 0.0, "end": 5.0,
             "text": "这是完全虚构的测试会议。我们决定星期五完成蓝色样机。"},
            {"speaker": "测试乙", "voice": None, "start": 5.0, "end": 9.0,
             "text": "同意，负责人使用虚构代号 Atlas。"},
        ], ensure_ascii=False), encoding="utf-8")
        minutes.write_text(
            "# 虚构测试会议\n\n## 总体摘要\n\n- 讨论了虚构样机。\n\n"
            "## 行动项\n\n- 暂无。\n", encoding="utf-8")

        tr_rev = assistant.revision(transcript)
        result = assistant.answer_question(
            root, "虚构会议决定什么时候完成什么？", [0, 1], tr_rev, [], False)
        if not result.get("answer") or "【R" not in result["answer"] or not result.get("sources"):
            print("[error] 问答未满足来源协议", file=sys.stderr)
            return 1
        proposal = assistant.preview_minutes_edit(
            minutes, transcript, "把虚构决定补充到行动项", [0, 1], tr_rev,
            assistant.revision(minutes), "## 行动项", False)
        if not proposal.get("proposal_id") or not proposal.get("diff"):
            print("[error] 修改预览未满足结构化协议", file=sys.stderr)
            return 1
        print(f"[meta] live assistant ok | sources={len(result['sources'])} "
              f"| target={proposal['target_heading']} | model={result['model']}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
