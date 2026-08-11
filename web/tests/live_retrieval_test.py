#!/usr/bin/env python3
"""用纯虚构中英混合会议验证常驻 embedding + reranker 与持久索引。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "web"))
import rag_service  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="meeting-retrieval-live-") as tmp:
        mdir = Path(tmp)
        turns = [
            {"speaker": "Synthetic A", "start": 1.0, "end": 4.0,
             "text": "The board approved the blue prototype for delivery on Friday."},
            {"speaker": "Synthetic B", "start": 5.0, "end": 7.0,
             "text": "大家讨论了午餐安排。"},
            {"speaker": "Synthetic C", "start": 8.0, "end": 11.0,
             "text": "预算风险仍然需要下周确认。"},
        ]
        (mdir / "transcript.spk.json").write_text(
            json.dumps(turns, ensure_ascii=False), encoding="utf-8")
        (mdir / "minutes.md").write_text(
            "# 虚构会议\n\n## 摘要\n\n这是用于检索协议的虚构数据。\n", encoding="utf-8")

        chinese = rag_service.retrieve(mdir, "谁批准周五交付蓝色样机？", [])
        english = rag_service.retrieve(mdir, "What budget risk still needs confirmation?", [])
        first_cn = next((source for source in chinese["sources"]
                         if source["type"] == "transcript"), {})
        first_en = next((source for source in english["sources"]
                         if source["type"] == "transcript"), {})
        indexes = list((mdir / ".rag").glob("*.json"))
        ok = (
            chinese.get("retrieval_mode") == "hybrid_reranked"
            and english.get("retrieval_mode") == "hybrid_reranked"
            and first_cn.get("turn_indexes") == [0]
            and first_en.get("turn_indexes") == [2]
            and first_cn.get("retrieval", {}).get("rerank_score") is not None
            and len(indexes) == 1
        )
        if not ok:
            print("[error] hybrid retrieval protocol failed", file=sys.stderr)
            return 1
        print("[meta] hybrid retrieval ok | mode=hybrid_reranked | index=1 | queries=2")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
