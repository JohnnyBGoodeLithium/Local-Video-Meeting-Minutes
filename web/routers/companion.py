"""Experimental Companion namespace; never grants access to the desktop API."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from fastapi import APIRouter, Cookie, Depends, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from companion_security import (CSRF_COOKIE, SESSION_COOKIE, CompanionStore, SessionGrant,
                                enabled)
import companion_projection
from deps import DATA_ROOT, MEETINGS, STATIC, _audio_path, _mdir, _video_path
from job_store import JOBS
from routers import jobs as job_routes

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


class LinkImport(BaseModel):
    url: str
    no_vl: bool = False


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


@router.get("/library")
def companion_library(_grant: SessionGrant = Depends(require("review"))):
    return {"items": companion_projection.library(MEETINGS)}


@router.get("/items/{item_id}")
def companion_item(item_id: str, _grant: SessionGrant = Depends(require("review"))):
    return companion_projection.item(_mdir(item_id))


@router.get("/items/{item_id}/people")
def companion_people(item_id: str, _grant: SessionGrant = Depends(require("review"))):
    return {"people": companion_projection.item(_mdir(item_id))["people"]}


@router.get("/items/{item_id}/people/{name}")
def companion_person(item_id: str, name: str,
                     _grant: SessionGrant = Depends(require("review"))):
    value = companion_projection.person(_mdir(item_id), name)
    if value is None:
        raise HTTPException(404, "Person not found in this item")
    return value


@router.get("/items/{item_id}/evidence/{evidence_id}")
def companion_evidence(item_id: str, evidence_id: str,
                       _grant: SessionGrant = Depends(require("review"))):
    value = companion_projection.item(_mdir(item_id))
    evidence = next((row for row in value["evidence"] if row["id"] == evidence_id), None)
    if evidence is None:
        raise HTTPException(404, "Evidence not found in this item")
    return {**evidence, "media_url": f"/api/companion/items/{item_id}/media/audio"}


@router.get("/items/{item_id}/media/{kind}")
def companion_media(item_id: str, kind: str,
                    _grant: SessionGrant = Depends(require("review"))):
    mdir = _mdir(item_id)
    path = _audio_path(mdir) if kind == "audio" else _video_path(mdir) if kind == "video" else None
    if path is None:
        raise HTTPException(404, "Approved meeting media unavailable")
    return FileResponse(path)


@router.get("/jobs/{job_id}")
def companion_job(job_id: str, _grant: SessionGrant = Depends(require("view_status"))):
    value = JOBS.get(job_id)
    if value is None:
        raise HTTPException(404, "Job not found")
    return companion_projection.job(value, JOBS.values())


@router.post("/import/url")
def companion_import_url(payload: LinkImport,
                         _grant: SessionGrant = Depends(require("send_url", write=True))):
    result = job_routes.import_media_url(job_routes.MediaURLImport(
        url=payload.url, no_vl=payload.no_vl))
    return companion_projection.job(result, [result])


@router.post("/import/file")
async def companion_import_file(file: UploadFile = File(...),
                                _grant: SessionGrant = Depends(require("upload", write=True))):
    max_bytes = int(os.environ.get("MEETING_COMPANION_UPLOAD_LIMIT", str(256 * 1024 * 1024)))
    result = await job_routes.upload_with_limit([file], "", "", "meeting",
                                                max_bytes=max_bytes)
    return companion_projection.job(result, [result])
