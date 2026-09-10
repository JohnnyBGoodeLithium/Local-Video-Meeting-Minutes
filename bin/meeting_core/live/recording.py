"""Durable segmented recording, independent of ASR and model latency."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def media_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


class LiveRecording:
    def __init__(self, meeting: Path, *, run=subprocess.run):
        self.meeting = meeting
        self.root = meeting / "live-recording"
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest = self.root / "manifest.json"
        self.run = run
        self.data = json.loads(self.manifest.read_text()) if self.manifest.exists() else {
            "schema": "meeting-live-recording/v1", "segments": [], "gaps": [],
            "state": "recording", "scope": "since_monitoring_started", "duration": 0,
        }
        self.epoch = None
        self.base = float(self.data["duration"])
        for epoch, base in self.data.get("epochs", {}).items():
            self.epoch, self.base = self.root / epoch, base
            self.scan()
        self.epoch = None

    def recover_tail(self):
        """Salvage an interrupted muxer's final TS, and label uncertain continuity."""
        known = {s["file"] for s in self.data["segments"]}
        for epoch in self.data.get("epochs", {}):
            for path in sorted((self.root / epoch).glob("*.ts")):
                relative = str(path.relative_to(self.root))
                if relative in known or not path.stat().st_size:
                    continue
                try:
                    result = self.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                       "-of", "default=nw=1:nk=1", str(path)],
                                      capture_output=True, timeout=10)
                    duration = float(result.stdout) if not result.returncode else 0
                    if not 0 < duration < 3600:
                        raise ValueError("invalid segment duration")
                    start = self.data["duration"]
                    self.data["segments"].append({"file": relative, "start": start,
                        "end": start + duration, "bytes": path.stat().st_size,
                        "sha256": media_hash(path), "recovered": True})
                    self.data["duration"] += duration
                    self.gap("recovered_unindexed_tail")
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    self.gap("unreadable_tail")
        self.save()

    def save(self):
        atomic_json(self.manifest, self.data)

    def begin(self, url: str) -> list[str]:
        # Unique epochs ensure restart/reconnect never overwrites prior media.
        self.epoch = self.root / uuid.uuid4().hex
        self.epoch.mkdir()
        self.base = float(self.data["duration"])
        self.data.setdefault("epochs", {})[self.epoch.name] = self.base
        self.data["state"] = "recording"
        self.save()
        return ["ffmpeg", "-nostdin", "-v", "error", "-rw_timeout", "15000000",
                "-i", url, "-map", "0:v:0?", "-map", "0:a:0?", "-c", "copy",
                "-f", "segment", "-segment_time", "10", "-reset_timestamps", "1",
                "-segment_list", str(self.epoch / "segments.csv"),
                "-segment_list_type", "csv", str(self.epoch / "%08d.ts")]

    def scan(self) -> list[dict]:
        if self.epoch is None or not (self.epoch / "segments.csv").exists():
            return []
        known = {s["file"] for s in self.data["segments"]}
        added = []
        raw = (self.epoch / "segments.csv").read_text()
        origin = None
        # Only complete CSV lines describe closed, safe-to-read segments.
        for line in raw.splitlines(keepends=True):
            if not line.endswith("\n"):
                continue
            row = next(csv.reader([line]))
            if len(row) != 3:
                continue
            name, start, end = row
            if origin is None:
                origin = float(start)
            path = self.epoch / Path(name).name
            if path.suffix != ".ts" or not path.is_file() or not path.stat().st_size:
                continue
            relative = str(path.relative_to(self.root))
            if relative in known:
                continue
            duration = max(0, float(end) - float(start))
            if not duration:
                continue
            item = {"file": relative, "start": self.base + float(start) - origin,
                    "end": self.base + float(end) - origin, "bytes": path.stat().st_size,
                    "sha256": media_hash(path)}
            self.data["segments"].append(item)
            self.data["duration"] = max(self.data["duration"], item["end"])
            known.add(relative)
            added.append(item)
        if added:
            self.save()
        return added

    def gap(self, reason: str, *, seconds: float | None = None):
        self.data["gaps"].append({"at": self.data["duration"], "reason": reason,
                                  "wall_time": time.time(), "seconds": seconds})
        self.save()

    def replay(self) -> Path | None:
        self.scan()
        segments = self.data["segments"]
        if not segments:
            self.data["state"] = "empty"
            self.save()
            return None
        for segment in segments:
            path = self.root / segment["file"]
            if not path.is_file() or path.stat().st_size != segment["bytes"] or (
                    segment.get("sha256") and media_hash(path) != segment["sha256"]):
                self.data["state"] = "segments_only"
                self.gap("segment_integrity_failure")
                return None
        # Paths are generated UUID + numeric names, never source-supplied strings.
        listing = self.root / "concat.txt"
        listing.write_text("".join(f"file '{s['file']}'\n" for s in segments))
        output = self.meeting / "source_video.mp4"
        pending = self.meeting / "source_video.pending.mp4"
        result = self.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "concat",
                           "-safe", "1", "-i", str(listing), "-c", "copy",
                           "-movflags", "+faststart", str(pending)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        if result.returncode == 0 and pending.is_file() and pending.stat().st_size:
            checked = self.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", str(pending)], capture_output=True, timeout=15)
            expected = sum(s["end"] - s["start"] for s in segments)
            try:
                actual = float(checked.stdout) if not checked.returncode else 0
            except ValueError:
                actual = 0
            if abs(actual - expected) > max(2, len(segments) * .1):
                self.data["state"] = "segments_only"
                self.gap("replay_duration_mismatch")
                return None
            os.replace(pending, output)
            self.data["state"] = "ready_with_gaps" if self.data["gaps"] else "ready"
            self.data["replay"] = output.name
            self.save()
            return output
        self.data["state"] = "segments_only"
        self.save()
        return None
