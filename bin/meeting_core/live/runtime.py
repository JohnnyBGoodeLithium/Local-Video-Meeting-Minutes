"""Background HLS session runtime for Experimental Live Context."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Callable

from meeting_core.asr import create_provider

from .asr import ASRChunk, ExistingASRProviderAdapter
from .capabilities import LiveSourceCapabilities
from .finalizer import LiveFinalizationError, mark_finalization_complete, prepare_finalization
from .fusion import fuse_text_signals
from .hls import HLSSubtitleSource, parse_media_playlist
from .models import TimedTextSignal
from .source import ProbedLiveSource, PublicSourceFetcher, SourceProbeError, probe_live_source
from .store import LiveSessionStore


class LiveRuntimeError(RuntimeError):
    """A live source cannot be started or finalized safely."""


class HLSBackgroundWorker:
    """Capture HLS without playback and keep analysis alive after the UI closes."""

    def __init__(self, source: ProbedLiveSource, meeting_dir: Path, *,
                 content_type: str, mode: str,
                 fetch: Callable[[str], tuple[str, str | None]] | None = None,
                 popen=subprocess.Popen, run=subprocess.run, sleep=time.sleep,
                 dry_run: bool = False, asr_provider_factory=create_provider):
        if source.source_kind != "hls" or not source.media_playlist_url:
            raise LiveRuntimeError("only native HLS can run in background in this phase")
        if source.capabilities.drm_detected:
            raise LiveRuntimeError("DRM-protected sources are unsupported")
        self.source = source
        self.store = LiveSessionStore(meeting_dir)
        self.content_type = content_type
        self.mode = mode
        self.fetch = fetch or PublicSourceFetcher()
        self.popen = popen
        self.run = run
        self.sleep = sleep
        self.dry_run = dry_run
        self.asr_provider_factory = asr_provider_factory
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.capture_process = None
        self.error: str | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.store.initialize(
            {"id": self.store.meeting_dir.name, "kind": "hls", "provisional": True,
             "content_type": self.content_type, "mode": self.mode},
            {"type": "hls", "url": self.source.source_url,
             "media_playlist_url": self.source.media_playlist_url,
             "subtitle_playlist_url": self.source.subtitle_playlist_url,
             "resolved_from_page": self.source.resolved_from_page,
             "capabilities": self.source.capabilities.to_dict()},
        )
        self.thread = threading.Thread(target=self._run, name="live-hls-worker", daemon=True)
        self.thread.start()

    def stop_and_finalize(self) -> None:
        self.stop_event.set()

    def status(self) -> dict:
        checkpoint = self.store.checkpoint()
        return {
            "id": self.store.meeting_dir.name,
            "state": checkpoint.get("state", "CONNECTING"),
            "duration": checkpoint.get("media_time", 0),
            "text_signals": checkpoint.get("text_signals", 0),
            "audio_lag_seconds": checkpoint.get("audio_backlog_seconds"),
            "visual_lag_seconds": checkpoint.get("vl_lag_seconds"),
            "error": self.error,
            "content_type": self.content_type,
            "mode": self.mode,
        }

    def workspace(self, *, limit: int = 120, signal_window: int = 480) -> dict:
        """Project private live signals into a bounded, user-facing workspace.

        The session list intentionally stays metadata-only. Transcript text is
        returned only from the explicit per-session workspace endpoint and the
        signed media playlist URL never leaves the worker.
        """
        bounded_limit = max(1, min(int(limit), 240))
        bounded_window = max(bounded_limit, min(int(signal_window), 960))
        signals = self.store.signals()
        recent_signals = signals[-bounded_window:]
        turns, _provenance = fuse_text_signals(
            recent_signals, max_turn_seconds=24.0, max_turn_chars=360)
        recent = turns[-bounded_limit:]
        return {
            "schema": "meeting-live-workspace/v1",
            "session": self.status(),
            "source": self.source.public_dict(),
            "transcript": {
                "turns": recent,
                "total_turns": len(turns),
                "signal_observations": len(signals),
                "truncated": len(signals) > len(recent_signals) or len(turns) > len(recent),
                "provisional": True,
            },
            "takeaways": {
                "state": "deferred_until_finalize",
                "items": [],
                "provisional": True,
            },
        }

    def _capture_command(self, capture: Path, with_pcm: bool) -> list[str]:
        command = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i",
                   self.source.media_playlist_url, "-map", "0", "-c", "copy", str(capture)]
        if with_pcm:
            command += ["-map", "0:a:0", "-ac", "1", "-ar", "16000",
                        "-f", "s16le", "pipe:1"]
        return command

    def _asr_reader(self, process) -> None:
        if process.stdout is None:
            return
        provider = ExistingASRProviderAdapter(self.asr_provider_factory(with_aligner=True))
        chunk_seconds, overlap_seconds, rate = 8.0, 1.0, 16000
        chunk_bytes = int(chunk_seconds * rate * 2)
        overlap_bytes = int(overlap_seconds * rate * 2)
        buffer = bytearray()
        start = 0.0
        while not self.stop_event.is_set():
            block = process.stdout.read(64 * 1024)
            if not block:
                break
            buffer.extend(block)
            while len(buffer) >= chunk_bytes:
                payload = bytes(buffer[:chunk_bytes])
                end = start + chunk_seconds
                began = time.monotonic()
                observations = provider.transcribe_chunk(ASRChunk(start, end, payload, rate))
                elapsed = time.monotonic() - began
                for index, item in enumerate(observations):
                    raw = f"{start:.3f}\0{index}\0{item.start:.3f}\0{item.text}"
                    self.store.append_signal(TimedTextSignal(
                        id=f"L{hashlib.sha256(raw.encode()).hexdigest()[:16]}",
                        start=item.start, end=item.end, text=item.text, speaker=None,
                        text_source="local_asr", speaker_source="unknown",
                        provisional=True, review_needed=True,
                    ))
                del buffer[:chunk_bytes - overlap_bytes]
                start += chunk_seconds - overlap_seconds
                checkpoint = self.store.checkpoint()
                self.store.save_checkpoint({
                    **checkpoint, "state": "LIVE", "media_time": end,
                    "text_signals": len(self.store.signals()),
                    "asr_lag_seconds": round(elapsed, 3),
                    "audio_backlog_seconds": round(len(buffer) / (rate * 2), 3),
                })

    def _run(self) -> None:
        asr_thread = None
        try:
            self.store.save_checkpoint({"state": "LIVE", "media_time": 0,
                                        "text_signals": len(self.store.signals())})
            capture = self.store.root / "capture.ts"
            needs_asr = not bool(self.source.subtitle_playlist_url)
            self.capture_process = self.popen(
                self._capture_command(capture, needs_asr),
                stdout=subprocess.PIPE if needs_asr else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True,
            )
            if needs_asr:
                asr_thread = threading.Thread(target=self._asr_reader,
                                              args=(self.capture_process,), daemon=True)
                asr_thread.start()
            subtitles = HLSSubtitleSource(
                self.store.checkpoint().get("subtitle_sequence"))
            last_sequence = self.store.checkpoint().get("media_sequence")
            target = max(0.5, self.source.target_duration)
            while not self.stop_event.is_set():
                raw, _mime = self.fetch(self.source.media_playlist_url)
                media = parse_media_playlist(raw, self.source.media_playlist_url)
                if media.segments:
                    current = media.segments[-1].sequence
                    progressed = last_sequence is None or current > last_sequence
                    last_sequence = max(current, last_sequence or current)
                else:
                    progressed = False
                if self.source.subtitle_playlist_url:
                    subtitle_raw, _subtitle_mime = self.fetch(self.source.subtitle_playlist_url)
                    signals, subtitle_state = subtitles.consume_playlist(
                        subtitle_raw, self.source.subtitle_playlist_url,
                        lambda url: self.fetch(url)[0])
                    self.store.append_signals(signals)
                    if subtitle_state.endlist:
                        media = subtitle_state
                media_time = max((item.end for item in self.store.signals()), default=0.0)
                self.store.save_checkpoint({
                    "state": "LIVE", "media_time": round(media_time, 3),
                    "text_signals": len(self.store.signals()),
                    "media_sequence": last_sequence,
                    "subtitle_sequence": subtitles.consumed_sequence,
                    "media_progressing": progressed,
                })
                if media.endlist:
                    break
                if self.capture_process.poll() is not None:
                    break
                target = media.target_duration
                self.sleep(max(0.5, target * 0.75))

            checkpoint = self.store.checkpoint()
            self.store.save_checkpoint({**checkpoint, "state": "ENDING",
                                        "end_signal": "user_stop" if self.stop_event.is_set()
                                        else "hls_endlist_or_media_end"})
            if self.capture_process.poll() is None:
                self.capture_process.terminate()
                try:
                    self.capture_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.capture_process.kill()
                    self.capture_process.wait(timeout=5)
            if asr_thread:
                asr_thread.join(timeout=30)
            source_media = None
            if capture.is_file() and capture.stat().st_size:
                source_media = self.store.meeting_dir / "source_video.ts"
                shutil.copyfile(capture, source_media)
            plan = prepare_finalization(
                self.store.meeting_dir, content_type=self.content_type,
                source_media=source_media)
            if not self.dry_run:
                for command in plan["commands"]:
                    result = self.run(command, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
                    if result.returncode:
                        raise LiveRuntimeError("canonical finalization stage failed")
            mark_finalization_complete(self.store.meeting_dir)
        except Exception as exc:
            self.error = type(exc).__name__
            try:
                checkpoint = self.store.checkpoint()
                self.store.save_checkpoint({**checkpoint, "state": "FAILED",
                                            "failure": self.error})
            except Exception:
                pass


class LiveSessionManager:
    def __init__(self):
        self._workers: dict[str, HLSBackgroundWorker] = {}
        self._lock = threading.Lock()

    def start_hls(self, source: ProbedLiveSource, meeting_dir: Path, *, content_type: str,
                  mode: str, dry_run: bool = False, **worker_options) -> dict:
        worker = HLSBackgroundWorker(source, meeting_dir, content_type=content_type,
                                     mode=mode, dry_run=dry_run, **worker_options)
        with self._lock:
            if meeting_dir.name in self._workers:
                raise LiveRuntimeError("live session already exists")
            self._workers[meeting_dir.name] = worker
        worker.start()
        return worker.status()

    def get(self, session_id: str) -> HLSBackgroundWorker | None:
        with self._lock:
            return self._workers.get(session_id)

    def list(self) -> list[dict]:
        with self._lock:
            return [worker.status() for worker in self._workers.values()]

    def stop(self, session_id: str) -> dict:
        worker = self.get(session_id)
        if worker is None:
            raise LiveRuntimeError("live session not found")
        worker.stop_and_finalize()
        return worker.status()

    def recover(self, meetings_root: Path, *, dry_run: bool = False) -> list[str]:
        """Resume checkpointed native-HLS sessions after a service restart."""
        recovered = []
        for meeting_dir in Path(meetings_root).glob("*/"):
            if self.get(meeting_dir.name) is not None:
                continue
            store = LiveSessionStore(meeting_dir)
            try:
                checkpoint = store.checkpoint()
                if checkpoint.get("state") not in {"CONNECTING", "LIVE", "STALLED", "RECOVERING"}:
                    continue
                source_data = json.loads((store.root / "source.json").read_text(encoding="utf-8"))
                session_data = json.loads((store.root / "session.json").read_text(encoding="utf-8"))
                if source_data.get("type") != "hls":
                    continue
                if source_data.get("resolved_from_page"):
                    source = probe_live_source(str(source_data["url"]))
                else:
                    capabilities_data = dict(source_data.get("capabilities") or {})
                    capabilities_data["end_detection"] = tuple(
                        capabilities_data.get("end_detection") or ())
                    source = ProbedLiveSource(
                        "hls", str(source_data["url"]),
                        LiveSourceCapabilities(**capabilities_data),
                        str(source_data["media_playlist_url"]),
                        (str(source_data["subtitle_playlist_url"])
                         if source_data.get("subtitle_playlist_url") else None),
                    )
                self.start_hls(
                    source, meeting_dir,
                    content_type=str(session_data.get("content_type") or "meeting"),
                    mode=str(session_data.get("mode") or "analyze_background"),
                    dry_run=dry_run,
                )
                recovered.append(meeting_dir.name)
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError,
                    LiveRuntimeError, SourceProbeError):
                continue
        return recovered
