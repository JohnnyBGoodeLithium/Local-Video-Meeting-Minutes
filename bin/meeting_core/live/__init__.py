"""Experimental Live Context domain primitives.

The live layer is deliberately non-canonical.  It records recoverable source
signals under ``meeting/.live`` and hands reconciled results to the existing
meeting pipeline only during finalization.
"""

from .models import TimedTextSignal
from .signals import generic_subtitle_signals, teams_cue_signals
from .store import LiveSessionStore

__all__ = [
    "LiveSessionStore",
    "TimedTextSignal",
    "generic_subtitle_signals",
    "teams_cue_signals",
]
