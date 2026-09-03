#!/usr/bin/env python3
"""Feature flag, same-origin, CSRF, admin-host and fake-header boundaries."""

import os
import sys
import tempfile
from pathlib import Path

from fastapi import HTTPException, Response
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(ROOT / "web"))

from companion_security import CompanionStore
from routers import companion


def request(*, host="testserver", origin=None, identity=None):
    headers = [(b"host", host.encode())]
    if origin:
        headers.append((b"origin", origin.encode()))
    if identity:
        headers.append((b"tailscale-user-login", identity.encode()))
    return Request({"type": "http", "method": "POST", "path": "/", "scheme": "https",
                    "server": (host, 443), "client": ("127.0.0.1", 1),
                    "headers": headers})


def rejected(call, status):
    try:
        call()
    except HTTPException as exc:
        assert exc.status_code == status, exc
    else:
        raise AssertionError(f"expected HTTP {status}")


with tempfile.TemporaryDirectory(prefix="mm-companion-security-") as tmp:
    companion.STORE = CompanionStore(Path(tmp) / "auth.json")
    os.environ.pop("MEETING_COMPANION", None)
    rejected(companion._feature, 404)

    os.environ["MEETING_COMPANION"] = "1"
    os.environ["MEETING_COMPANION_PUBLIC_BASE"] = "https://x-ultra.example.ts.net"
    local = request()
    companion._local_admin(local)
    rejected(lambda: companion._local_admin(request(host="device.example.ts.net")), 404)
    rejected(lambda: companion._same_origin(request(origin="https://evil.invalid")), 403)
    companion._same_origin(request(origin="https://testserver"))

    pairing = companion.create_pairing(local)
    assert pairing["pairing_url"].startswith("https://x-ultra.example.ts.net/companion#pair=")
    assert "?" not in pairing["pairing_url"], "pairing token must stay in the URL fragment"
    requested = companion.request_pairing(
        companion.PairRequest(token=pairing["token"], display_name="Synthetic phone"),
        request(origin="https://testserver", identity="fake@example.test"))
    companion.decide_pairing(companion.PairDecision(
        request_id=requested["request_id"], allow=True))
    response = Response()
    connected = companion.pairing_status(
        companion.PairStatus(request_id=requested["request_id"], token=pairing["token"]),
        request(origin="https://testserver"), response)
    assert connected["state"] == "connected"
    cookies = response.headers.getlist("set-cookie")
    assert len(cookies) == 2 and all("Secure" in item for item in cookies)
    session_cookie = next(item for item in cookies if "meeting_companion_session=" in item)
    token = session_cookie.split("=", 1)[1].split(";", 1)[0]
    grant = companion._session(token)
    rejected(lambda: companion._write_session(
        request(origin="https://testserver"), grant, "", "csrf"), 403)
    assert companion._write_session(
        request(origin="https://testserver"), grant, "csrf", "csrf") == grant

    # A direct request cannot promote a forged Tailscale header into app authorization.
    rejected(lambda: companion._session(""), 401)
    state = Path(tmp, "auth.json").read_text(encoding="utf-8")
    assert "fake@example.test" in state and pairing["token"] not in state

print("companion security: flag, origin, CSRF, host and fake headers passed")
