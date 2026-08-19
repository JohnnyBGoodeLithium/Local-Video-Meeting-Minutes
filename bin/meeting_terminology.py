#!/usr/bin/env python3
"""本地会议术语候选维护；stdout 只输出数量，不输出术语或会议正文。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from meeting_core.terminology import configured_bank_dir, harvest_screen_candidates


ROOT = Path(__file__).resolve().parent.parent


def _meeting_title(path: Path) -> str:
    try:
        import json
        value = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        title = " ".join(str(value.get("title") or "").split())
        if title:
            return title
    except Exception:
        pass
    return path.name


def main() -> int:
    parser = argparse.ArgumentParser(description="从共享画面沉淀 ASR 术语候选")
    parser.add_argument("mode", choices=("harvest", "backfill"))
    parser.add_argument("path", type=Path, help="会议目录，或 backfill 时的 meetings 根目录")
    parser.add_argument("--title", default="")
    parser.add_argument("--bank-dir", type=Path, default=configured_bank_dir(ROOT))
    args = parser.parse_args()

    if args.mode == "harvest":
        if not args.path.is_dir():
            print("会议目录不存在", file=sys.stderr)
            return 2
        try:
            result = harvest_screen_candidates(
                args.path, args.title or _meeting_title(args.path), args.bank_dir)
        except Exception as exc:
            print(f"[meta] 术语候选提取失败: {type(exc).__name__}", file=sys.stderr)
            return 1
        print(f"[meta] 术语候选 {result['state']} | 新增 {result['added']} | 更新 {result['updated']}"
              f" | 总数 {result['total']}")
        return 0

    if not args.path.is_dir():
        print("meetings 根目录不存在", file=sys.stderr)
        return 2
    meetings = sorted(path for path in args.path.iterdir() if path.is_dir()
                      and (path / "page_desc.json").is_file())
    ok = failed = added = updated = 0
    for meeting in meetings:
        try:
            result = harvest_screen_candidates(meeting, _meeting_title(meeting), args.bank_dir)
            ok += 1
            added += result["added"]
            updated += result["updated"]
        except Exception as exc:
            failed += 1
            print(f"[meta] 一场历史会议候选提取失败: {type(exc).__name__}", file=sys.stderr)
    print(f"[meta] 历史术语回填 | 成功 {ok} | 失败 {failed} | 新增 {added} | 更新 {updated}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
