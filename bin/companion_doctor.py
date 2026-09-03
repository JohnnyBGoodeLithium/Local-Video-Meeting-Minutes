#!/usr/bin/env python3
"""Read-only Tailscale Serve readiness checks for Experimental Companion."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from typing import Callable


Runner = Callable[[list[str]], tuple[int, str]]


def run(command: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return result.returncode, result.stdout


def _json(text: str) -> dict:
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _contains_funnel(value) -> bool:
    if isinstance(value, dict):
        return any(("funnel" in str(key).lower() and bool(item)) or _contains_funnel(item)
                   for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_funnel(item) for item in value)
    return "funnel" in str(value).lower() and "off" not in str(value).lower()


def recommended_command(help_text: str, port: int) -> str | None:
    """Only recommend syntax advertised by the installed CLI help."""
    if "<target>" not in help_text and "http://127.0.0.1" not in help_text:
        return None
    background = " --bg" if "--bg" in help_text else ""
    return f"tailscale serve{background} http://127.0.0.1:{port}"


def diagnose(*, runner: Runner = run, which: Callable[[str], str | None] = shutil.which,
             port: int = 8899, feature_enabled: bool | None = None,
             backend_probe: Callable[[int], bool] | None = None) -> dict:
    installed = which("tailscale") is not None
    status, serve_help, serve_status = {}, "", {}
    if installed:
        rc, output = runner(["tailscale", "status", "--json"])
        status = _json(output) if rc == 0 else {}
        _, serve_help = runner(["tailscale", "serve", "--help"])
        _, serve_output = runner(["tailscale", "serve", "status", "--json"])
        serve_status = _json(serve_output)
        if not serve_status:
            _, plain = runner(["tailscale", "serve", "status"])
            serve_status = {"plain": plain[:1000]}
    connected = bool(status) and (status.get("BackendState") == "Running"
                                   or bool((status.get("Self") or {}).get("Online")))
    dns_name = str((status.get("Self") or {}).get("DNSName") or "")
    magic_dns = bool(dns_name.endswith(".ts.net."))
    probe = backend_probe or probe_backend
    return {
        "tailscale_installed": installed,
        "tailscale_connected": connected,
        "serve_available": bool(serve_help and "serve" in serve_help.lower()),
        "magic_dns_ready": magic_dns,
        "https_ready": magic_dns and connected,
        "backend_localhost": probe(port),
        "companion_enabled": (os.environ.get("MEETING_COMPANION", "0") == "1"
                              if feature_enabled is None else feature_enabled),
        "public_funnel_detected": _contains_funnel(serve_status),
        "suggested_command": recommended_command(serve_help, port),
    }


def probe_backend(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=.4):
            return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("MEETING_WEB_PORT", 8899)))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    value = diagnose(port=args.port)
    if args.json:
        print(json.dumps(value, indent=2))
        return 0
    labels = {
        "tailscale_installed": "Tailscale installed", "tailscale_connected": "Tailscale connected",
        "serve_available": "Serve available", "magic_dns_ready": "HTTPS/MagicDNS ready",
        "backend_localhost": "Backend localhost", "companion_enabled": "Companion feature enabled",
        "public_funnel_detected": "Public Funnel detected",
    }
    for key, label in labels.items():
        print(f"{label}: {'yes' if value[key] else 'no'}")
    if value["public_funnel_detected"]:
        print("WARNING: Public Funnel is enabled. Do not use Funnel for Companion meeting data.")
    if value["suggested_command"]:
        print("Suggested command based on this installed Tailscale version:")
        print(value["suggested_command"])
    elif not value["tailscale_installed"]:
        print("Install and connect Tailscale on this device first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
