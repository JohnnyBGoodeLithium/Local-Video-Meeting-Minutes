#!/usr/bin/env python3
"""短插话保留与声纹标签抖动过滤的纯虚构回归。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from diarize import assign_speakers, coalesce_turns, smooth_dia, to_turns  # noqa: E402


def char(text, start, end):
    return {"text": text, "start_time": start, "end_time": end}


# Speaker B 在稍后有稳定发言：夹在 A 中间的单字短插话必须保留。
segments = [
    (0.0, 2.0, "A"),
    (2.0, 2.55, "B"),
    (2.55, 4.0, "A"),
    (5.0, 8.0, "B"),
]
chars = [
    char("主", 0.2, 0.4),
    char("对", 2.1, 2.3),
    char("续", 2.8, 3.0),
    char("补", 5.2, 5.4),
]
smoothed = smooth_dia(segments, chars=chars)
assert smoothed[1] == (2.0, 2.55, "B"), smoothed
turns = to_turns(assign_speakers(chars, smoothed))
assert [item["speaker"] for item in turns] == ["A", "B", "A", "B"], turns


# 只出现一次、夹在 A 中间且只有一个字符的新标签仍按声纹抖动处理。
flicker = [(0.0, 2.0, "A"), (2.0, 2.4, "NOISE"), (2.4, 4.0, "A")]
smoothed = smooth_dia(flicker, chars=[char("词", 2.1, 2.2)])
assert smoothed == [(0.0, 4.0, "A")], smoothed


# 一次性短发言若有两个可读字符，不因说话人只出现一次而被吞掉。
one_off = [(0.0, 2.0, "A"), (2.0, 2.7, "B"), (2.7, 4.0, "A")]
smoothed = smooth_dia(one_off, chars=[char("好", 2.1, 2.25), char("的", 2.3, 2.5)])
assert [item[2] for item in smoothed] == ["A", "B", "A"], smoothed


# 没有任何 ASR 文字落在短段内时仍应平滑，避免恢复无声碎片。
silent = [(0.0, 2.0, "A"), (2.0, 2.6, "B"), (2.6, 4.0, "A"), (5.0, 7.0, "B")]
smoothed = smooth_dia(silent, chars=[char("前", 1.0, 1.2)])
assert smoothed[:2] == [(0.0, 4.0, "A"), (5.0, 7.0, "B")], smoothed


# 同一人物的短碎片仍可合并，但不能把长口播重新吞成从 00:00 开始的唯一 turn。
short = [
    {"speaker": "A", "start": 0.0, "end": 4.0, "text": "第一句。"},
    {"speaker": "A", "start": 4.2, "end": 8.0, "text": "第二句。"},
]
assert len(coalesce_turns(short)) == 1
long = [
    {"speaker": "A", "start": index * 20.0, "end": (index + 1) * 20.0,
     "text": "虚构的连续口播段落。" * 8}
    for index in range(6)
]
coalesced = coalesce_turns(long)
assert len(coalesced) >= 3, coalesced
assert max(item["end"] - item["start"] for item in coalesced) <= 45.0

print("diarization short-turn tests: PASS")
