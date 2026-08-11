#!/usr/bin/env python3
"""为会议目录预建本地向量索引，不打印会议正文。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

import rag_service  # noqa: E402
import retrieval_models  # noqa: E402


def build_all(meetings_dir: Path) -> dict:
    meetings_dir = meetings_dir.resolve()
    built = cached = skipped = failed = records_total = 0
    failures = []
    for mdir in sorted(path for path in meetings_dir.iterdir() if path.is_dir()):
        if not (mdir / "transcript.spk.json").is_file():
            skipped += 1
            continue
        if not any((mdir / name).is_file() for name in ("minutes.md", "minutes.spk.md")):
            skipped += 1
            continue
        try:
            records, _meta = rag_service.meeting_records(mdir)
            result = retrieval_models.ensure_index(mdir, records)
            records_total += int(result.get("count", 0))
            if result.get("state") == "built":
                built += 1
            elif result.get("state") == "cached":
                cached += 1
            else:
                skipped += 1
        except Exception as exc:  # 单个坏会议不阻塞其余会议预热
            failed += 1
            failures.append({"meeting": mdir.name, "error": type(exc).__name__})
    return {
        "schema": "meeting-rag-index-build/v1",
        "model": retrieval_models.EMBED_MODEL,
        "built": built,
        "cached": cached,
        "skipped": skipped,
        "failed": failed,
        "records": records_total,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meetings-dir", type=Path, default=ROOT / "meetings")
    args = parser.parse_args()
    if not args.meetings_dir.is_dir():
        parser.error(f"会议目录不存在: {args.meetings_dir}")
    result = build_all(args.meetings_dir)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
