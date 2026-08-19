"""标准纪要之上的可切换 AI 阅读视图。

`minutes.md` 始终是 canonical；整篇重组只写 `minutes.views.json`。视图绑定
标准纪要与事实层 revision，来源变化后保留记录但不再作为可用视图返回。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from pathlib import Path

import assistant_service


SCHEMA = "meeting-minutes-views/v1"
MAX_VIEWS = 12


def _path(mdir: Path) -> Path:
    return mdir / "minutes.views.json"


def _read(mdir: Path) -> dict:
    path = _path(mdir)
    if not path.is_file():
        return {"schema": SCHEMA, "views": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": SCHEMA, "views": []}
    if value.get("schema") != SCHEMA or not isinstance(value.get("views"), list):
        return {"schema": SCHEMA, "views": []}
    return value


def _write(mdir: Path, value: dict) -> None:
    path = _path(mdir)
    fd, raw = tempfile.mkstemp(prefix="minutes-views-", suffix=".json", dir=mdir)
    tmp = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def save_view(mdir: Path, *, markdown: str, summary: str,
              instruction: str, minutes_revision: str,
              sources: list[dict]) -> dict:
    now = time.time()
    view = {
        "id": uuid.uuid4().hex[:12],
        "title": str(summary or "AI 重组纪要").strip()[:80],
        "summary": str(summary or "").strip()[:300],
        "instruction": str(instruction or "").strip()[:1000],
        "markdown": str(markdown),
        "minutes_revision": minutes_revision,
        "facts_revision": assistant_service.revision(mdir / "meeting.facts.json"),
        "sources": sources,
        "created_at": now,
    }
    data = _read(mdir)
    data["views"] = [view, *data["views"]][:MAX_VIEWS]
    _write(mdir, data)
    return view


def list_views(mdir: Path, minutes_revision: str | None) -> list[dict]:
    facts_revision = assistant_service.revision(mdir / "meeting.facts.json")
    result = []
    for item in _read(mdir).get("views", []):
        if item.get("minutes_revision") != minutes_revision:
            continue
        if item.get("facts_revision") != facts_revision:
            continue
        result.append(item)
    return result
