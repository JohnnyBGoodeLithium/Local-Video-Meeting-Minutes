#!/usr/bin/env python3
"""Headless/background browser modes require measured capability."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.browser import (BrowserCapabilityTest, BrowserEndSignals,
                                       BrowserExecution, plan_browser_capture)


foreground = plan_browser_capture("watch_analyze")
assert foreground.execution == BrowserExecution.FOREGROUND
assert foreground.muted_output is False

unknown = plan_browser_capture("analyze_background")
assert unknown.execution == BrowserExecution.UNSUPPORTED
assert unknown.action_required == "keep_source_window_open"
assert unknown.muted_output is True

partial = BrowserCapabilityTest(True, True, True, False)
headless = plan_browser_capture("analyze_background", partial, prefer_headless=True)
assert headless.execution == BrowserExecution.UNSUPPORTED

verified = BrowserCapabilityTest(True, True, True, True)
headless = plan_browser_capture("analyze_background", verified, prefer_headless=True)
assert headless.execution == BrowserExecution.HEADLESS_VERIFIED
assert headless.muted_output is True and headless.keep_source_window_open is False

signals = BrowserEndSignals(source_is_vod=True, media_progressing=False)
assert signals.strong_end and signals.live_to_vod

print("browser capture tests: OK")
