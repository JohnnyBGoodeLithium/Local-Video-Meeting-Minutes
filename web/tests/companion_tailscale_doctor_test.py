#!/usr/bin/env python3
"""Tailscale doctor uses fake metadata and never performs network mutations."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))
import companion_doctor as doctor  # noqa: E402


calls = []


def runner(command):
    calls.append(command)
    key = tuple(command[1:])
    values = {
        ("status", "--json"): (0, '{"BackendState":"Running","Self":{"Online":true,"DNSName":"x.synthetic.ts.net."}}'),
        ("serve", "--help"): (0, "USAGE: tailscale serve [flags] <target>\n --bg"),
        ("serve", "status", "--json"): (0, '{"TCP":{"443":{"HTTPS":true}},"AllowFunnel":true}'),
    }
    return values.get(key, (1, ""))


value = doctor.diagnose(runner=runner, which=lambda _name: "/bin/tailscale", port=8899,
                        feature_enabled=True, backend_probe=lambda port: port == 8899)
assert value["tailscale_connected"] and value["magic_dns_ready"] and value["https_ready"]
assert value["public_funnel_detected"] is True
assert value["suggested_command"] == "tailscale serve --bg http://127.0.0.1:8899"
assert all("login" not in command and "funnel" not in command for command in calls)
assert doctor.recommended_command("legacy syntax unknown", 8899) is None
missing = doctor.diagnose(runner=runner, which=lambda _name: None,
                          backend_probe=lambda _port: False)
assert not missing["tailscale_installed"] and missing["suggested_command"] is None

print("companion Tailscale doctor: detection, current-help command and Funnel warning passed")
