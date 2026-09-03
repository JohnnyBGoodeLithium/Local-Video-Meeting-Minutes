"""Source capability and capture-plan contracts for Experimental Live Context."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


LIVE_MODES = {"analyze_background", "watch_analyze", "meeting_companion", "manual"}


@dataclass(frozen=True, slots=True)
class LiveSourceCapabilities:
    native_video: bool = False
    native_audio: bool = False
    native_subtitle: bool = False
    browser_required: bool = False
    authentication_required: bool = False
    background_safe: bool = False
    browser_background_safe: bool | None = None
    audio_capture_method: str = "unavailable"
    subtitle_method: str = "unavailable"
    drm_detected: bool = False
    end_detection: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["end_detection"] = list(self.end_detection)
        return value


@dataclass(frozen=True, slots=True)
class CapturePlan:
    content_type: str
    requested_mode: str
    mode: str
    video: str
    audio: str
    text: str
    browser: str
    background_available: bool
    audible_playback: bool = False
    consent_required: bool = False
    action_required: str | None = None
    limitations: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.content_type not in {"meeting", "live_event"}:
            raise ValueError("unsupported live content type")
        if self.requested_mode not in LIVE_MODES or self.mode not in LIVE_MODES:
            raise ValueError("unsupported live mode")
        if self.requested_mode == "analyze_background" and self.mode != self.requested_mode:
            raise ValueError("background mode cannot silently switch")
        if self.mode in {"analyze_background", "meeting_companion"} and self.audible_playback:
            raise ValueError("background analysis cannot require audible playback")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["limitations"] = list(self.limitations)
        return value


def default_mode(content_type: str) -> str:
    if content_type == "live_event":
        return "analyze_background"
    if content_type == "meeting":
        return "meeting_companion"
    raise ValueError("unsupported live content type")


def build_capture_plan(content_type: str, capabilities: LiveSourceCapabilities,
                       requested_mode: str | None = None) -> CapturePlan:
    """Choose methods without silently converting background work to playback."""
    requested = requested_mode or default_mode(content_type)
    if requested not in LIVE_MODES:
        raise ValueError("unsupported live mode")
    if capabilities.drm_detected:
        return CapturePlan(
            content_type=content_type, requested_mode=requested, mode=requested,
            video="unsupported", audio="unsupported", text="unsupported", browser="none",
            background_available=False, action_required="unsupported_drm",
            limitations=("drm_protected_source",),
        )

    if content_type == "meeting":
        mode = requested
        browser = "external_meeting_client" if mode == "meeting_companion" else "user_managed"
        audio = capabilities.audio_capture_method
        consent = audio == "system_loopback"
        unavailable = audio in {"", "unavailable"}
        return CapturePlan(
            content_type=content_type, requested_mode=requested, mode=mode,
            video="delayed_screen_capture",
            audio=audio,
            text=("native_transcript" if capabilities.native_subtitle
                  else "caption_or_local_asr"),
            browser=browser,
            background_available=not unavailable and not consent,
            consent_required=consent,
            action_required=("confirm_system_audio" if consent else
                             "configure_audio_capture" if unavailable else None),
            limitations=(("may_capture_other_applications",) if consent else ()),
        )

    native_background = (capabilities.native_audio and capabilities.background_safe
                         and not capabilities.browser_required)
    browser_background = (capabilities.browser_required
                          and capabilities.browser_background_safe is True
                          and capabilities.audio_capture_method not in {"", "unavailable"})
    background_available = native_background or browser_background
    if requested == "analyze_background" and not background_available:
        return CapturePlan(
            content_type=content_type, requested_mode=requested, mode=requested,
            video="native_hls" if capabilities.native_video else "browser",
            audio="unavailable",
            text=("native_subtitle" if capabilities.native_subtitle else "visual_caption"),
            browser="required_open" if capabilities.browser_required else "none",
            background_available=False,
            action_required="open_source_and_analyze",
            limitations=("background_capture_unavailable",),
        )
    return CapturePlan(
        content_type=content_type, requested_mode=requested, mode=requested,
        video=("native_hls" if capabilities.native_video else "browser"),
        audio=(capabilities.audio_capture_method if capabilities.native_audio
               or capabilities.browser_required else "unavailable"),
        text=("native_subtitle" if capabilities.native_subtitle
              else "visual_caption" if capabilities.browser_required else "local_asr"),
        browser=("none" if native_background else
                 "foreground" if requested == "watch_analyze" else "background_headful"),
        background_available=background_available,
        audible_playback=requested == "watch_analyze",
    )
