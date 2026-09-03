"""Multi-signal end detection with stall recovery and a grace period."""

from __future__ import annotations

from dataclasses import dataclass

from .state import LiveSourceState, LiveStateMachine


@dataclass(frozen=True, slots=True)
class EndDecision:
    state: LiveSourceState
    reason: str | None = None
    finalize: bool = False
    live_to_vod: bool = False


class LiveEndDetector:
    def __init__(self, *, stall_seconds: float = 90, grace_seconds: float = 45):
        if stall_seconds <= 0 or grace_seconds < 0:
            raise ValueError("invalid end-detection timing")
        self.stall_seconds = stall_seconds
        self.grace_seconds = grace_seconds
        self.machine = LiveStateMachine()
        self.last_progress_at: float | None = None
        self.ending_at: float | None = None

    def connected(self, now: float) -> EndDecision:
        self.last_progress_at = now
        self.machine.transition(LiveSourceState.LIVE, "connected")
        return EndDecision(self.machine.state, self.machine.reason)

    def observe(self, now: float, *, progressed: bool = False, endlist: bool = False,
                media_ended: bool = False, live_to_vod: bool = False) -> EndDecision:
        if self.machine.state in {LiveSourceState.COMPLETE, LiveSourceState.FAILED,
                                  LiveSourceState.CANCELLED, LiveSourceState.FINALIZING}:
            return EndDecision(self.machine.state, self.machine.reason)
        if endlist or media_ended or live_to_vod:
            if self.machine.state not in {LiveSourceState.ENDING}:
                self.machine.transition(LiveSourceState.ENDING,
                                        "hls_endlist" if endlist else
                                        "live_to_vod" if live_to_vod else "media_ended")
            self.ending_at = now
            return EndDecision(self.machine.state, self.machine.reason,
                               finalize=True, live_to_vod=live_to_vod)
        if progressed:
            self.last_progress_at = now
            self.ending_at = None
            if self.machine.state == LiveSourceState.STALLED:
                self.machine.transition(LiveSourceState.RECOVERING, "progress_resumed")
                self.machine.transition(LiveSourceState.LIVE, "recovered")
            elif self.machine.state == LiveSourceState.ENDING:
                self.machine.transition(LiveSourceState.LIVE, "progress_resumed")
            return EndDecision(self.machine.state, self.machine.reason)
        if self.last_progress_at is None:
            self.last_progress_at = now
        idle = now - self.last_progress_at
        if idle >= self.stall_seconds and self.machine.state == LiveSourceState.LIVE:
            self.machine.transition(LiveSourceState.STALLED, "media_progress_stalled")
        if idle >= self.stall_seconds + self.grace_seconds:
            if self.machine.state == LiveSourceState.STALLED:
                self.machine.transition(LiveSourceState.ENDING, "possibly_ended")
                self.ending_at = now
            elif (self.machine.state == LiveSourceState.ENDING and self.ending_at is not None
                  and now - self.ending_at >= self.grace_seconds):
                return EndDecision(self.machine.state, self.machine.reason, finalize=True)
        return EndDecision(self.machine.state, self.machine.reason)
