"""Crash-recoverable, non-canonical storage for an active live session."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any, Iterable

from .models import TimedTextSignal


LIVE_SCHEMA = "meeting-live-runtime/v1"


class LiveStoreError(RuntimeError):
    """A live runtime path or payload violated the storage contract."""


class LiveSessionStore:
    """Own ``meeting/.live`` append logs and atomic snapshots.

    JSONL recovery ignores a final torn line, which allows a process to resume
    after interruption without accepting partially written source facts.
    """

    def __init__(self, meeting_dir: Path):
        self.meeting_dir = Path(meeting_dir).resolve()
        self.root = self.meeting_dir / ".live"

    def initialize(self, session: dict[str, Any], source: dict[str, Any]) -> None:
        self.meeting_dir.mkdir(parents=True, exist_ok=True)
        self.root.mkdir(mode=0o700, exist_ok=True)
        self._atomic_json("session.json", {"schema": LIVE_SCHEMA, **session})
        self._atomic_json("source.json", {"schema": LIVE_SCHEMA, **source})
        if not (self.root / "checkpoint.json").exists():
            self.save_checkpoint({"state": "CONNECTING", "media_time": 0.0,
                                  "text_signals": 0})

    def _path(self, name: str) -> Path:
        if Path(name).name != name or name not in {
            "session.json", "source.json", "checkpoint.json",
            "text-signals.jsonl", "speaker-events.jsonl", "frame-events.jsonl",
            "metrics.jsonl",
        }:
            raise LiveStoreError("unsupported live runtime path")
        return self.root / name

    def _atomic_json(self, name: str, value: dict[str, Any]) -> None:
        path = self._path(name)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)

    def append(self, name: str, value: dict[str, Any]) -> None:
        path = self._path(name)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)

    def read_jsonl(self, name: str) -> list[dict[str, Any]]:
        path = self._path(name)
        if not path.is_file():
            return []
        values = []
        lines = path.read_bytes().splitlines(keepends=True)
        for index, raw in enumerate(lines):
            if index == len(lines) - 1 and not raw.endswith((b"\n", b"\r")):
                break
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise LiveStoreError(f"corrupt complete JSONL record in {name}") from exc
            if not isinstance(value, dict):
                raise LiveStoreError(f"non-object JSONL record in {name}")
            values.append(value)
        return values

    def append_signal(self, signal: TimedTextSignal) -> bool:
        existing = {item.get("id") for item in self.read_jsonl("text-signals.jsonl")}
        if signal.id in existing:
            return False
        self.append("text-signals.jsonl", signal.to_dict())
        return True

    def signals(self) -> list[TimedTextSignal]:
        return [TimedTextSignal.from_dict(item)
                for item in self.read_jsonl("text-signals.jsonl")]

    def save_checkpoint(self, value: dict[str, Any]) -> None:
        self._atomic_json("checkpoint.json", {"schema": LIVE_SCHEMA, **value})

    def checkpoint(self) -> dict[str, Any]:
        path = self._path("checkpoint.json")
        if not path.is_file():
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != LIVE_SCHEMA:
            raise LiveStoreError("unsupported live checkpoint")
        return value

    def append_signals(self, signals: Iterable[TimedTextSignal]) -> int:
        return sum(1 for signal in signals if self.append_signal(signal))

    def write_frame(self, frame_id: str, content: bytes, *, at: float, reason: str,
                    suffix: str = ".jpg") -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", frame_id):
            raise LiveStoreError("unsafe live frame id")
        if suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise LiveStoreError("unsupported live frame format")
        frames = self.root / "frames"
        frames.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = frames / f"{frame_id}{suffix.lower()}"
        temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        temp.write_bytes(content)
        os.replace(temp, path)
        self.append("frame-events.jsonl", {
            "id": frame_id, "at": round(float(at), 3), "reason": reason,
            "file": f"frames/{path.name}",
        })
        return path
