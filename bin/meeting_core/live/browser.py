"""Browser-assisted capture policy; browser execution is an adapter, not the product."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BrowserExecution(StrEnum):
    FOREGROUND = "foreground"
    BACKGROUND_HEADFUL = "background_headful"
    HEADLESS_VERIFIED = "headless_verified"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class BrowserCapabilityTest:
    media_continues: bool
    audio_continues: bool
    captions_continue: bool
    no_background_throttling: bool

    @property
    def headless_safe(self) -> bool:
        return all((self.media_continues, self.audio_continues,
                    self.captions_continue, self.no_background_throttling))


@dataclass(frozen=True, slots=True)
class BrowserCapturePlan:
    execution: BrowserExecution
    muted_output: bool
    keep_source_window_open: bool
    action_required: str | None = None


def plan_browser_capture(mode: str, capability: BrowserCapabilityTest | None = None,
                         *, prefer_headless: bool = False) -> BrowserCapturePlan:
    if mode == "watch_analyze":
        return BrowserCapturePlan(BrowserExecution.FOREGROUND, False, True)
    if mode != "analyze_background":
        raise ValueError("unsupported browser capture mode")
    if prefer_headless:
        if capability is None or not capability.headless_safe:
            return BrowserCapturePlan(BrowserExecution.UNSUPPORTED, True, True,
                                      "keep_source_window_open")
        return BrowserCapturePlan(BrowserExecution.HEADLESS_VERIFIED, True, False)
    if capability is None or not capability.media_continues or not capability.audio_continues:
        return BrowserCapturePlan(BrowserExecution.UNSUPPORTED, True, True,
                                  "keep_source_window_open")
    return BrowserCapturePlan(BrowserExecution.BACKGROUND_HEADFUL, True, True)


@dataclass(frozen=True, slots=True)
class BrowserEndSignals:
    media_ended: bool = False
    live_ui_ended: bool = False
    source_is_vod: bool = False
    media_progressing: bool = True

    @property
    def strong_end(self) -> bool:
        return self.media_ended or self.live_ui_ended or self.source_is_vod

    @property
    def live_to_vod(self) -> bool:
        return self.source_is_vod
