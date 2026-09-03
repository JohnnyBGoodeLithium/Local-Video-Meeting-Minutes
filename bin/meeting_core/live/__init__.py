"""Experimental Live Context domain primitives.

The live layer is deliberately non-canonical.  It records recoverable source
signals under ``meeting/.live`` and hands reconciled results to the existing
meeting pipeline only during finalization.
"""

from .capabilities import CapturePlan, LiveSourceCapabilities, build_capture_plan, default_mode
from .models import TimedTextSignal
from .state import LiveSourceState, LiveStateMachine
from .signals import generic_subtitle_signals, teams_cue_signals
from .store import LiveSessionStore

__all__ = [
    "LiveSessionStore",
    "LiveSourceCapabilities",
    "CapturePlan",
    "LiveSourceState",
    "LiveStateMachine",
    "TimedTextSignal",
    "build_capture_plan",
    "default_mode",
    "generic_subtitle_signals",
    "teams_cue_signals",
]
