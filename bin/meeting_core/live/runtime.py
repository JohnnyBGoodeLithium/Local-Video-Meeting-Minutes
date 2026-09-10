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
from .recording import LiveRecording
from .evidence import LiveEvidence


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
        self.recording = LiveRecording(meeting_dir, run=run)
        self.recording.recover_tail()
        self.recording_done = threading.Event()
        self.analysis_done = threading.Event()
        self.frames_done = threading.Event()
        self.checkpoint_lock = threading.RLock()
        self.evidence = None
        self.bookmark_requested = threading.Event()
        self.suspend_event = threading.Event()


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

    def suspend(self):
        self.suspend_event.set()
        self.stop_event.set()
        self._stop_capture()

    def status(self) -> dict:
        checkpoint = self.store.checkpoint()
        return {
            "id": self.store.meeting_dir.name,
            "state": checkpoint.get("state", "CONNECTING"),
            "duration": checkpoint.get("media_time", 0),
            "text_signals": checkpoint.get("text_signals", 0),
            "audio_lag_seconds": checkpoint.get("audio_backlog_seconds"),
            "visual_lag_seconds": checkpoint.get("vl_lag_seconds"),
            "error": self.error or checkpoint.get("failure"),
            "content_type": self.content_type,
            "mode": self.mode,
            "recording_state": self.recording.data["state"],
            "gaps": len(self.recording.data["gaps"]),
            "analysis_error": checkpoint.get("analysis_error"),
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
            "takeaways": self.evidence.topics if self.evidence else {
                "state": "collecting", "items": [], "provisional": True},
            "frames": [{"id": f["id"], "at": f["at"], "reason": f["reason"]}
                       for f in self.store.read_jsonl("frame-events.jsonl")[-120:]],
            "recording": {**self.recording.data,
                          "segments": [{"index": i, "start": s["start"], "end": s["end"]}
                                       for i, s in enumerate(self.recording.data["segments"])]},
        }

    def _checkpoint(self, **values):
        with self.checkpoint_lock:
            self.store.save_checkpoint({**self.store.checkpoint(), **values})

    def _stop_capture(self):
        process = self.capture_process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def _analyze_segments(self):
        try:
            if self.source.subtitle_playlist_url or self.dry_run:
                return
            provider = ExistingASRProviderAdapter(self.asr_provider_factory(with_aligner=True))
            done = set(self.store.checkpoint().get("analyzed_segments", []))
            while not self.suspend_event.is_set():
                pending = [s for s in list(self.recording.data["segments"]) if s["file"] not in done]
                for segment in pending:
                    path = self.recording.root / segment["file"]
                    result = self.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
                                       "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"],
                                      capture_output=True, timeout=30)
                    if result.returncode or not result.stdout:
                        raise LiveRuntimeError("recorded segment audio decode failed")
                    pcm = result.stdout
                    for offset in range(0, len(pcm), 7 * 32000):
                        payload = pcm[offset:offset + 8 * 32000]
                        if len(payload) < 3200:
                            continue
                        start = segment["start"] + offset / 32000
                        end = min(segment["end"], start + len(payload) / 32000)
                        if end <= start:
                            continue
                        began = time.monotonic()
                        observations = provider.transcribe_chunk(ASRChunk(start, end, payload, 16000))
                        for index, item in enumerate(observations):
                            raw = f"{segment['file']}:{offset}:{index}:{item.text}"
                            self.store.append_signal(TimedTextSignal(
                                id=f"L{hashlib.sha256(raw.encode()).hexdigest()[:16]}",
                                start=item.start, end=item.end, text=item.text, speaker=None,
                                text_source="local_asr", speaker_source="unknown",
                                provisional=True, review_needed=True))
                        self._checkpoint(asr_lag_seconds=round(time.monotonic() - began, 3))
                    done.add(segment["file"])
                    self._checkpoint(analyzed_segments=sorted(done), analyzed_until=segment["end"],
                                     text_signals=len(self.store.signals()))
                if self.recording_done.is_set() and not pending:
                    break
                time.sleep(.2)
        except Exception as exc:
            self._checkpoint(analysis_error=type(exc).__name__)
        finally:
            self.analysis_done.set()

    def _capture_frames(self):
        seen = set()
        while not self.suspend_event.is_set():
            pending = [s for s in list(self.recording.data["segments"]) if s["file"] not in seen]
            for segment in pending:
                try:
                    force = self.bookmark_requested.is_set()
                    if self.evidence.capture(self.recording.root / segment["file"], segment["start"], force=force):
                        self.bookmark_requested.clear()
                    self._checkpoint(frame_error=None)
                except Exception as exc:
                    self._checkpoint(frame_error=type(exc).__name__)
                seen.add(segment["file"])
            if self.recording_done.is_set() and not pending:
                break
            time.sleep(.2)
        self.frames_done.set()

    def _topics(self):
        while not self.suspend_event.is_set():
            complete = (self.recording_done.is_set() and self.analysis_done.is_set()
                        and self.frames_done.is_set())
            turns, _ = fuse_text_signals(self.store.signals())
            until = max((t["end"] for t in turns), default=0)
            if not complete and self.recording.data["duration"] - until > 20:
                time.sleep(1)
                continue
            self.evidence.update_topic(turns, until, force=complete)
            if complete:
                break
            self.analysis_done.wait(1) if not self.analysis_done.is_set() else time.sleep(1)

    def _run(self) -> None:
        threads = []
        interrupted = bool(self.recording.data["segments"])
        self.evidence = LiveEvidence(self.store, run=self.run)
        try:
            if interrupted:
                self.recording.gap("service_restart")
            self._checkpoint(state="LIVE", media_time=self.recording.data["duration"])
            if not self.dry_run:
                for target in (self._analyze_segments, self._capture_frames, self._topics):
                    thread = threading.Thread(target=target, daemon=True)
                    thread.start()
                    threads.append(thread)
            else:
                self.analysis_done.set()
            retries = 0
            subtitles = HLSSubtitleSource(self.store.checkpoint().get("subtitle_sequence"))
            while not self.stop_event.is_set():
                command = self.recording.begin(self.source.media_playlist_url)
                self.capture_process = self.popen(command, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, start_new_session=True)
                ended = False
                last_progress = time.monotonic()
                last_sequence = None
                try:
                    while not self.stop_event.is_set():
                        self.recording.scan()
                        self._checkpoint(media_time=self.recording.data["duration"],
                                         text_signals=len(self.store.signals()))
                        try:
                            raw, _ = self.fetch(self.source.media_playlist_url)
                            media = parse_media_playlist(raw, self.source.media_playlist_url)
                            if media.drm_detected:
                                raise LiveRuntimeError("protected playlist")
                            sequence = media.segments[-1].sequence if media.segments else None
                            if sequence != last_sequence:
                                last_progress = time.monotonic()
                                last_sequence = sequence
                            if self.source.subtitle_playlist_url:
                                raw_sub, _ = self.fetch(self.source.subtitle_playlist_url)
                                signals, _ = subtitles.consume_playlist(raw_sub, self.source.subtitle_playlist_url,
                                    lambda url: self.fetch(url)[0])
                                self.store.append_signals(signals)
                                self._checkpoint(subtitle_sequence=subtitles.consumed_sequence)
                            if media.endlist:
                                ended = True
                                if not self.dry_run:
                                    try:
                                        self.capture_process.wait(timeout=30)
                                    except subprocess.TimeoutExpired:
                                        self.recording.gap("end_drain_timeout")
                                break
                            if time.monotonic() - last_progress > 60:
                                break
                        except (OSError, ValueError, SourceProbeError):
                            if time.monotonic() - last_progress > 60:
                                break
                        if self.capture_process.poll() is not None:
                            break
                        self.sleep(max(.5, min(2, self.source.target_duration * .5)))
                finally:
                    self._stop_capture()
                    self.recording.scan()
                if ended or self.stop_event.is_set():
                    break
                retries += 1
                self.recording.gap("connection_interrupted")
                self._checkpoint(state="RECOVERING")
                if retries > 3:
                    raise LiveRuntimeError("reconnect limit reached; recording retained")
                if self.stop_event.wait(min(10, retries * 2)):
                    break
                fresh = probe_live_source(self.source.source_url)
                if fresh.source_kind != "hls":
                    raise LiveRuntimeError("source no longer offers HLS")
                self.source = fresh
                self._checkpoint(state="LIVE")
        except Exception as exc:
            self.error = type(exc).__name__
            self._checkpoint(capture_error=self.error)
        finally:
            try:
                self._stop_capture()
                self.recording.scan()
                if not self.dry_run:
                    self.recording.recover_tail()
                self._checkpoint(state="ENDING", text_signals=len(self.store.signals()),
                                 end_signal="user_stop" if self.stop_event.is_set() else "source_end")
            except Exception as exc:
                self.error = type(exc).__name__
            finally:
                self.recording_done.set()
        if self.suspend_event.is_set():
            self._checkpoint(state="RECOVERING", failure="service_shutdown")
            return
        # Publish the recording even when ASR, OCR or final synthesis fails.
        try:
            replay = None if self.dry_run else self.recording.replay()
            if not self.dry_run and replay is None:
                self.error = "ReplayUnavailable"
                self._checkpoint(replay_error=self.error)
        except Exception as exc:
            replay = None
            self.error = type(exc).__name__
            self.recording.data["state"] = "segments_only"
            self.recording.save()
            self._checkpoint(replay_error=type(exc).__name__)
        for thread in threads:
            thread.join()  # recording is already durable; analysis may catch up after stop
        if self.suspend_event.is_set():
            self._checkpoint(state="FAILED", failure="interrupted_finalization")
            return
        try:
            if self.store.checkpoint().get("analysis_error"):
                raise LiveRuntimeError("analysis incomplete; replay retained")
            if self.error:
                raise LiveRuntimeError("capture incomplete; replay retained")
            plan = prepare_finalization(self.store.meeting_dir, content_type=self.content_type,
                                        source_media=replay)
            if not self.dry_run:
                for command in plan["commands"]:
                    result = self.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if result.returncode:
                        raise LiveRuntimeError("canonical finalization stage failed")
            mark_finalization_complete(self.store.meeting_dir)
        except Exception as exc:
            self.error = type(exc).__name__
            self._checkpoint(state="FAILED", failure=self.error)


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

    def shutdown(self):
        for worker in list(self._workers.values()):
            if worker.thread and worker.thread.is_alive():
                worker.suspend()
        for worker in list(self._workers.values()):
            if worker.thread and worker.thread.is_alive():
                worker.thread.join(timeout=3)

    def recover(self, meetings_root: Path, *, dry_run: bool = False) -> list[str]:
        """Resume checkpointed native-HLS sessions after a service restart."""
        recovered = []
        for meeting_dir in Path(meetings_root).glob("*/"):
            if self.get(meeting_dir.name) is not None:
                continue
            store = LiveSessionStore(meeting_dir)
            try:
                checkpoint = store.checkpoint()
                if not checkpoint:
                    continue
                source_data = json.loads((store.root / "source.json").read_text(encoding="utf-8"))
                session_data = json.loads((store.root / "session.json").read_text(encoding="utf-8"))
                if source_data.get("type") != "hls":
                    continue
                active = checkpoint.get("state") in {"CONNECTING", "LIVE", "STALLED", "RECOVERING"}
                if source_data.get("resolved_from_page") and active:
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
                options = {"content_type": str(session_data.get("content_type") or "meeting"),
                           "mode": str(session_data.get("mode") or "analyze_background"),
                           "dry_run": dry_run}
                if active:
                    self.start_hls(source, meeting_dir, **options)
                else:
                    worker = HLSBackgroundWorker(source, meeting_dir, **options)
                    worker.recording_done.set()
                    worker.analysis_done.set()
                    worker.evidence = LiveEvidence(store)
                    if checkpoint.get("state") in {"ENDING", "FINALIZING"}:
                        worker._checkpoint(state="FAILED", failure="interrupted_finalization")
                    with self._lock:
                        self._workers[meeting_dir.name] = worker
                recovered.append(meeting_dir.name)
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError,
                    LiveRuntimeError, SourceProbeError):
                continue
        return recovered
