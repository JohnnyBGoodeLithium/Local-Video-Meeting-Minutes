#!/usr/bin/env python3
"""Background-first capture plans never silently switch to playback."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.capabilities import (LiveSourceCapabilities, build_capture_plan,
                                            default_mode)


assert default_mode("live_event") == "analyze_background"
assert default_mode("meeting") == "meeting_companion"

hls = LiveSourceCapabilities(
    native_video=True, native_audio=True, native_subtitle=True,
    background_safe=True, audio_capture_method="native_hls",
    subtitle_method="native_hls", end_detection=("hls_endlist",),
)
plan = build_capture_plan("live_event", hls)
assert plan.mode == "analyze_background"
assert plan.browser == "none" and plan.audible_playback is False
assert plan.audio == "native_hls" and plan.text == "native_subtitle"

browser_unknown = LiveSourceCapabilities(
    browser_required=True, browser_background_safe=None,
    audio_capture_method="browser_capture", subtitle_method="visual_caption",
)
blocked = build_capture_plan("live_event", browser_unknown)
assert blocked.mode == "analyze_background"
assert blocked.background_available is False
assert blocked.action_required == "open_source_and_analyze"
assert blocked.audible_playback is False

watch = build_capture_plan("live_event", browser_unknown, "watch_analyze")
assert watch.mode == "watch_analyze" and watch.browser == "foreground"
assert watch.audible_playback is True

meeting = build_capture_plan("meeting", LiveSourceCapabilities(
    audio_capture_method="system_loopback"))
assert meeting.mode == "meeting_companion"
assert meeting.consent_required is True
assert meeting.action_required == "confirm_system_audio"
assert meeting.audible_playback is False

drm = build_capture_plan("live_event", LiveSourceCapabilities(drm_detected=True))
assert drm.action_required == "unsupported_drm"

print("live source plan tests: OK")
