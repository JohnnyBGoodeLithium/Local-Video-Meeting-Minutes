"""每场会议的逐轮人工身份锁。

声纹 ``person_id`` 表示跨会议的常规身份；这里记录用户明确确认过的具体轮次，
供后续相似扩散跳过。文件只保存索引、时间指纹和内部 ID，不保存逐字稿正文。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = "speaker-corrections/v1"
FILE_NAME = "speaker.corrections.json"


def turn_ref(index: int, turn: dict) -> str:
    start = round(float(turn.get("start", 0)), 3)
    end = round(float(turn.get("end", start)), 3)
    return f"{int(index)}:{start:.3f}:{end:.3f}"


def load(mdir: Path) -> dict:
    path = mdir / FILE_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema": SCHEMA, "locks": []}
    if data.get("schema") != SCHEMA or not isinstance(data.get("locks"), list):
        return {"schema": SCHEMA, "locks": []}
    return data


def locked_indexes(mdir: Path, turns: list[dict]) -> set[int]:
    refs = {item.get("turn_ref") for item in load(mdir).get("locks", [])}
    return {index for index, turn in enumerate(turns) if turn_ref(index, turn) in refs}


def lock_turns(mdir: Path, turns: list[dict], indexes: list[int], *,
               person_id: str | None, voice_id: str | None, operation: str) -> None:
    data = load(mdir)
    by_ref = {item.get("turn_ref"): item for item in data.get("locks", [])
              if item.get("turn_ref")}
    now = datetime.now(timezone.utc).isoformat()
    for index in sorted({int(value) for value in indexes if 0 <= int(value) < len(turns)}):
        ref = turn_ref(index, turns[index])
        by_ref[ref] = {
            "turn_ref": ref,
            "person_id": person_id,
            "voice_id": voice_id,
            "operation": operation,
            "updated_at": now,
        }
    data = {"schema": SCHEMA, "locks": sorted(by_ref.values(), key=lambda item: item["turn_ref"])}
    path = mdir / FILE_NAME
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

