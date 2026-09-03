"""Experimental Companion namespace; never grants access to the desktop API."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel

from companion_security import (CSRF_COOKIE, SESSION_COOKIE, CompanionStore, SessionGrant,
                                enabled)
from deps import DATA_ROOT

router = APIRouter(prefix="/api/companion")
STORE = CompanionStore(Path(os.environ.get(
    "MEETING_COMPANION_STATE", DATA_ROOT / "companion" / "auth.json")))


def _feature() -> None:
    if not enabled():
        raise HTTPException(404, "Companion unavailable")


def _local_admin(request: Request) -> None:
    _feature()
    host = (request.headers.get("host") or "").split(":", 1)[0].strip("[]").lower()
    if host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        raise HTTPException(404, "Companion unavailable")


def _same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    host = request.headers.get("host")
    if not origin or not host:
        raise HTTPException(403, "Same-origin request required")
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.casefold() != host.casefold():
        raise HTTPException(403, "Origin rejected")


def _session(session_token: str = Cookie("", alias=SESSION_COOKIE)) -> SessionGrant:
    _feature()
    grant = STORE.authenticate(session_token)
    if grant is None:
        raise HTTPException(401, "Companion connection revoked or unavailable")
    return grant


def _write_session(request: Request, grant: SessionGrant = Depends(_session),
                   csrf_header: str = Header("", alias="X-CSRF-Token"),
                   csrf_cookie: str = Cookie("", alias=CSRF_COOKIE)) -> SessionGrant:
    _same_origin(request)
    if not csrf_header or not csrf_cookie or not secrets.compare_digest(csrf_header, csrf_cookie):
        raise HTTPException(403, "CSRF validation failed")
    return grant


def require(capability: str, *, write: bool = False):
    dependency = _write_session if write else _session

    def check(grant: SessionGrant = Depends(dependency)) -> SessionGrant:
        if capability not in grant.capabilities:
            raise HTTPException(403, "Companion capability denied")
        return grant
    return check


class PairRequest(BaseModel):
    token: str
    display_name: str = "Mobile Companion"


class PairStatus(BaseModel):
    token: str
    request_id: str


class PairDecision(BaseModel):
    request_id: str
    allow: bool


@router.post("/admin/pairings", dependencies=[Depends(_local_admin)])
def create_pairing(request: Request):
    item = STORE.create_pairing()
    public_base = os.environ.get("MEETING_COMPANION_PUBLIC_BASE", "").rstrip("/")
    pairing_url = f"{public_base}/companion?pair={item['token']}" if public_base else None
    return {**item, "pairing_url": pairing_url}


@router.get("/admin/requests", dependencies=[Depends(_local_admin)])
def pairing_requests():
    return {"requests": STORE.pending()}


@router.post("/admin/decide", dependencies=[Depends(_local_admin)])
def decide_pairing(payload: PairDecision):
    try:
        STORE.decide(payload.request_id, payload.allow)
    except ValueError as exc:
        raise HTTPException(409, "Pairing request is no longer pending") from exc
    return {"ok": True, "state": "approved" if payload.allow else "denied"}


@router.get("/admin/sessions", dependencies=[Depends(_local_admin)])
def paired_sessions():
    return {"sessions": STORE.sessions()}


@router.post("/admin/sessions/{session_id}/revoke", dependencies=[Depends(_local_admin)])
def revoke_session(session_id: str):
    if not STORE.revoke(session_id):
        raise HTTPException(404, "Companion device not found")
    return {"ok": True}


@router.post("/pair/request", dependencies=[Depends(_feature)])
def request_pairing(payload: PairRequest, request: Request):
    _same_origin(request)
    identity = {
        "login": (request.headers.get("tailscale-user-login") or "")[:120],
        "name": (request.headers.get("tailscale-user-name") or "")[:120],
    }
    try:
        return STORE.request_pairing(payload.token, payload.display_name, identity=identity)
    except ValueError as exc:
        status = 409 if str(exc) == "already_used" else 410
        raise HTTPException(status, "Pairing code is invalid, expired, or already used") from exc


@router.post("/pair/status", dependencies=[Depends(_feature)])
def pairing_status(payload: PairStatus, request: Request, response: Response):
    _same_origin(request)
    state, claim = STORE.pairing_status(payload.request_id, payload.token, claim=True)
    if claim:
        secure = os.environ.get("MEETING_COMPANION_INSECURE_TEST_COOKIE") != "1"
        response.set_cookie(SESSION_COOKIE, claim["token"], secure=secure, httponly=True,
                            samesite="strict", path="/api/companion")
        csrf = secrets.token_urlsafe(24)
        response.set_cookie(CSRF_COOKIE, csrf, secure=secure, httponly=False,
                            samesite="strict", path="/")
        return {"state": "connected", "session": {
            "id": claim["session"]["id"],
            "display_name": claim["session"]["display_name"],
            "capabilities": claim["session"]["capabilities"],
        }}
    return {"state": state}


@router.get("/session")
def current_session(grant: SessionGrant = Depends(_session)):
    return {"id": grant.id, "display_name": grant.display_name,
            "capabilities": grant.capabilities}
