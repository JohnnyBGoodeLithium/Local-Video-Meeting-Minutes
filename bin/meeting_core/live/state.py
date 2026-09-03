"""Explicit live source state machine; logs are never the state source."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LiveSourceState(StrEnum):
    CONNECTING = "CONNECTING"
    LIVE = "LIVE"
    STALLED = "STALLED"
    RECOVERING = "RECOVERING"
    ENDING = "ENDING"
    FINALIZING = "FINALIZING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TRANSITIONS = {
    LiveSourceState.CONNECTING: {LiveSourceState.LIVE, LiveSourceState.FAILED,
                                 LiveSourceState.CANCELLED},
    LiveSourceState.LIVE: {LiveSourceState.STALLED, LiveSourceState.ENDING,
                           LiveSourceState.FAILED, LiveSourceState.CANCELLED},
    LiveSourceState.STALLED: {LiveSourceState.RECOVERING, LiveSourceState.ENDING,
                              LiveSourceState.FAILED, LiveSourceState.CANCELLED},
    LiveSourceState.RECOVERING: {LiveSourceState.LIVE, LiveSourceState.STALLED,
                                 LiveSourceState.ENDING, LiveSourceState.FAILED,
                                 LiveSourceState.CANCELLED},
    LiveSourceState.ENDING: {LiveSourceState.LIVE, LiveSourceState.FINALIZING,
                             LiveSourceState.FAILED, LiveSourceState.CANCELLED},
    LiveSourceState.FINALIZING: {LiveSourceState.COMPLETE, LiveSourceState.FAILED,
                                 LiveSourceState.CANCELLED},
    LiveSourceState.COMPLETE: set(),
    LiveSourceState.FAILED: set(),
    LiveSourceState.CANCELLED: set(),
}


@dataclass(slots=True)
class LiveStateMachine:
    state: LiveSourceState = LiveSourceState.CONNECTING
    reason: str | None = None

    def transition(self, target: LiveSourceState | str, reason: str | None = None) -> None:
        target = LiveSourceState(target)
        if target not in TRANSITIONS[self.state]:
            raise ValueError(f"invalid live transition: {self.state} -> {target}")
        self.state = target
        self.reason = reason

    def to_dict(self) -> dict[str, str | None]:
        return {"state": self.state.value, "reason": self.reason}
