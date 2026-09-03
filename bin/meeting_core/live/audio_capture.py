"""Audio capture policy and host capability probing for Live Context.

This module never starts capture while probing.  In particular, it does not
create a system-wide loopback or reroute a user's current audio session.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import shutil
import subprocess
from typing import Callable, Protocol


class AudioCaptureError(RuntimeError):
    """Requested capture would be unavailable or cross a consent boundary."""


@dataclass(frozen=True, slots=True)
class AudioCaptureCapability:
    provider: str
    available: bool
    per_application: bool
    silent_output: bool
    consent_required: bool
    reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class AudioCaptureProvider(Protocol):
    name: str

    def capability(self) -> AudioCaptureCapability: ...

    def capture_command(self, *, consent: bool = False) -> list[str]: ...


class NativeStreamAudioCapture:
    name = "native_stream"

    def __init__(self, stream_url: str):
        self.stream_url = stream_url

    def capability(self) -> AudioCaptureCapability:
        return AudioCaptureCapability(self.name, bool(self.stream_url), True, True, False,
                                      None if self.stream_url else "missing_stream")

    def capture_command(self, *, consent: bool = False) -> list[str]:
        if not self.stream_url:
            raise AudioCaptureError("native audio stream is unavailable")
        return ["ffmpeg", "-nostdin", "-v", "error", "-i", self.stream_url,
                "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"]


class PipeWireBrowserCapture:
    """Plan capture through a dedicated null sink; never route to speakers."""

    name = "pipewire_browser"
    sink_name = "meeting_live_context"

    def __init__(self, *, available: bool, reason: str | None = None):
        self.available = available
        self.reason = reason

    def capability(self) -> AudioCaptureCapability:
        return AudioCaptureCapability(
            self.name, self.available, True, True, False, self.reason)

    def setup_commands(self) -> list[list[str]]:
        if not self.available:
            raise AudioCaptureError(self.reason or "PipeWire browser capture unavailable")
        return [[
            "pactl", "load-module", "module-null-sink",
            f"sink_name={self.sink_name}", "sink_properties=device.description=MeetingLiveContext",
        ]]

    def capture_command(self, *, consent: bool = False) -> list[str]:
        if not self.available:
            raise AudioCaptureError(self.reason or "PipeWire browser capture unavailable")
        return ["ffmpeg", "-nostdin", "-v", "error", "-f", "pulse", "-i",
                f"{self.sink_name}.monitor", "-ac", "1", "-ar", "16000",
                "-f", "s16le", "pipe:1"]


class SystemLoopbackCapture:
    name = "system_loopback"

    def __init__(self, device: str = "default.monitor", *, available: bool = True):
        self.device = device
        self.available = available

    def capability(self) -> AudioCaptureCapability:
        return AudioCaptureCapability(
            self.name, self.available, False, True, True,
            "may_capture_other_applications" if self.available else "loopback_unavailable")

    def capture_command(self, *, consent: bool = False) -> list[str]:
        if not self.available:
            raise AudioCaptureError("system loopback unavailable")
        if not consent:
            raise AudioCaptureError("system-wide audio capture requires explicit consent")
        return ["ffmpeg", "-nostdin", "-v", "error", "-f", "pulse", "-i", self.device,
                "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"]


class FakeAudioCapture:
    name = "fake"

    def capability(self) -> AudioCaptureCapability:
        return AudioCaptureCapability(self.name, True, True, True, False)

    def capture_command(self, *, consent: bool = False) -> list[str]:
        return ["fake-audio-capture"]


def probe_host_audio(*, which: Callable[[str], str | None] = shutil.which,
                     run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> dict:
    """Inspect PipeWire/Pulse compatibility without changing audio routes."""
    tools = {name: bool(which(name)) for name in ("pactl", "pw-cli", "wpctl", "ffmpeg")}
    server = None
    if tools["pactl"]:
        try:
            result = run(["pactl", "info"], capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.lower().startswith("server name:"):
                        server = line.split(":", 1)[1].strip()
                        break
        except (OSError, subprocess.SubprocessError):
            server = None
    pipewire = bool(server and "pipewire" in server.lower())
    pulse_compatible = bool(server)
    dedicated = bool(tools["ffmpeg"] and tools["pactl"] and (pipewire or pulse_compatible))
    provider = PipeWireBrowserCapture(
        available=dedicated,
        reason=None if dedicated else "dedicated_sink_tools_unavailable",
    )
    return {
        "tools": tools,
        "audio_server": "pipewire" if pipewire else "pulse" if pulse_compatible else None,
        "browser_capture": provider.capability().to_dict(),
        "system_loopback": SystemLoopbackCapture(available=pulse_compatible).capability().to_dict(),
    }
