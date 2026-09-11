"""Deterministic per-pass visual work selection; never deletes source evidence."""
from __future__ import annotations


def select_pages(pages: list[dict], descriptions: dict, limit: int) -> list[dict]:
    pending = [p for p in pages if not str(descriptions.get(int(p['page']), '')).strip()]
    pending.sort(key=lambda p: (float(p.get('first', 0)), int(p['page'])))
    if limit <= 0 or len(pending) <= limit:
        return pending
    # Reserve temporal coverage, including both ends. Fill remaining slots with
    # content rather than repeated talking-head candidates. Neither is semantic proof.
    slots = min(limit, max(2, (limit + 1) // 2))
    start, end = float(pending[0].get('first', 0)), float(pending[-1].get('first', 0))
    selected = {}
    for i in range(slots):
        target = start + (end - start) * i / max(1, slots - 1)
        p = min(pending, key=lambda p: (abs(float(p.get('first', 0)) - target), int(p['page'])))
        selected[int(p['page'])] = p
    for p in sorted(pending, key=lambda p: (bool(p.get('talking_head')), float(p.get('first', 0)))):
        if len(selected) >= limit:
            break
        selected.setdefault(int(p['page']), p)
    return sorted(selected.values(), key=lambda p: (float(p.get('first', 0)), int(p['page'])))
