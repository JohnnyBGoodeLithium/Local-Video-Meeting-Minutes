#!/usr/bin/env python3
"""Audio capture defaults remain silent and system-wide capture needs consent."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.live.audio_capture import (AudioCaptureError, FakeAudioCapture,
                                             NativeStreamAudioCapture, PipeWireBrowserCapture,
                                             SystemLoopbackCapture, probe_host_audio)


native = NativeStreamAudioCapture("https://example.invalid/audio.m3u8?token=private")
assert native.capability().silent_output is True
assert "pipe:1" in native.capture_command()

pipewire = PipeWireBrowserCapture(available=True)
assert pipewire.capability().per_application is True
assert pipewire.capability().consent_required is False
assert all("speaker" not in part.lower() for part in pipewire.capture_command())
assert pipewire.sink_name in " ".join(pipewire.setup_commands()[0])

loopback = SystemLoopbackCapture()
assert loopback.capability().consent_required is True
try:
    loopback.capture_command()
except AudioCaptureError:
    pass
else:
    raise AssertionError("system-wide loopback started without consent")
assert loopback.capture_command(consent=True)[0] == "ffmpeg"
assert FakeAudioCapture().capability().silent_output is True

def fake_which(name):
    return f"/usr/bin/{name}" if name in {"pactl", "pw-cli", "wpctl", "ffmpeg"} else None

def fake_run(command, **_kwargs):
    assert command == ["pactl", "info"]
    return subprocess.CompletedProcess(command, 0, stdout="Server Name: PulseAudio (on PipeWire)\n")

probe = probe_host_audio(which=fake_which, run=fake_run)
assert probe["audio_server"] == "pipewire"
assert probe["browser_capture"]["available"] is True
assert probe["browser_capture"]["silent_output"] is True

missing = probe_host_audio(which=lambda _name: None)
assert missing["browser_capture"]["available"] is False
assert missing["system_loopback"]["available"] is False

print("audio capture policy tests: OK")
