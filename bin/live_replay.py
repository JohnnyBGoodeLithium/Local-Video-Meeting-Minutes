#!/usr/bin/env python3
"""Replay a local media file as an Experimental Live Context source."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from meeting_core.live.replay import ReplayError, replay


ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay local media as live context")
    parser.add_argument("media", type=Path)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--meeting-dir", type=Path)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--subtitle", type=Path)
    parser.add_argument("--caption-region", help="Reserved relative x,y,width,height region")
    parser.add_argument("--no-vl", action="store_true")
    parser.add_argument("--num-speakers", type=int)
    args = parser.parse_args()
    meeting_dir = args.meeting_dir or ROOT / "meetings" / f"live-replay-{args.media.stem}"
    try:
        result = replay(
            args.media, meeting_dir, speed=args.speed, transcript=args.transcript,
            subtitle=args.subtitle, no_vl=args.no_vl, num_speakers=args.num_speakers,
        )
    except ReplayError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    # Runtime paths are private; CLI emits counts/state only.
    print(json.dumps({key: value for key, value in result.items() if key != "live_dir"},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
