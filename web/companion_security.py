"""Application pairing and least-privilege device sessions for Companion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any


DEFAULT_CAPABILITIES = (
    "send_url", "upload", "view_status", "review", "speaker_confirm",
)
PAIR_TTL_SECONDS = 300
SESSION_COOKIE = "meeting_companion_session"
CSRF_COOKIE = "meeting_companion_csrf"


def enabled() -> bool:
    return os.environ.get("MEETING_COMPANION", "0") == "1"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now_iso(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class SessionGrant:
    id: str
    display_name: str
    capabilities: tuple[str, ...]


class CompanionStore:
    """Small hashed-token store; no meeting text, paths, or tailnet secrets."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        return {
            "schema": "companion-auth/v1",
            "pairings": data.get("pairings", []) if isinstance(data.get("pairings"), list) else [],
            "sessions": data.get("sessions", []) if isinstance(data.get("sessions"), list) else [],
        }

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def create_pairing(self, *, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        token = secrets.token_urlsafe(24)
        item = {
            "id": secrets.token_hex(8), "token_hash": _hash(token),
            "short_code": f"{secrets.randbelow(1_000_000):06d}",
            "created_at": _now_iso(now), "expires_at": now + PAIR_TTL_SECONDS,
            "state": "issued", "request": None,
        }
        with self.lock:
            data = self._read()
            data["pairings"] = [entry for entry in data["pairings"]
                                if float(entry.get("expires_at") or 0) > now][-20:]
            data["pairings"].append(item)
            self._write(data)
        return {"id": item["id"], "token": token, "short_code": item["short_code"],
                "expires_at": item["expires_at"]}

    def request_pairing(self, token: str, display_name: str, *, identity: dict | None = None,
                        now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        with self.lock:
            data = self._read()
            pairing = next((item for item in data["pairings"]
                            if secrets.compare_digest(str(item.get("token_hash") or ""),
                                                      _hash(token))), None)
            if pairing is None or float(pairing.get("expires_at") or 0) <= now:
                raise ValueError("invalid_or_expired")
            if pairing.get("state") != "issued":
                raise ValueError("already_used")
            request_id = secrets.token_hex(8)
            pairing["state"] = "pending"
            pairing["request"] = {
                "id": request_id, "display_name": display_name[:80] or "Mobile Companion",
                "requested_at": _now_iso(now), "identity": identity or {},
            }
            self._write(data)
            return {"request_id": request_id, "expires_at": pairing["expires_at"]}

    def pending(self, *, now: float | None = None) -> list[dict[str, Any]]:
        now = time.time() if now is None else now
        with self.lock:
            data = self._read()
        return [{"pairing_id": item["id"],
                 "request_id": item["request"]["id"],
                 **{key: value for key, value in item["request"].items() if key != "id"},
                 "expires_at": item["expires_at"]}
                for item in data["pairings"] if item.get("state") == "pending"
                and item.get("request") and float(item.get("expires_at") or 0) > now]

    def decide(self, request_id: str, allow: bool, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self.lock:
            data = self._read()
            pairing = next((item for item in data["pairings"]
                            if (item.get("request") or {}).get("id") == request_id), None)
            if pairing is None or pairing.get("state") != "pending":
                raise ValueError("not_pending")
            if float(pairing.get("expires_at") or 0) <= now:
                pairing["state"] = "expired"
                self._write(data)
                raise ValueError("invalid_or_expired")
            pairing["state"] = "approved" if allow else "denied"
            self._write(data)

    def pairing_status(self, request_id: str, token: str, *, claim: bool = False,
                       now: float | None = None) -> tuple[str, dict[str, Any] | None]:
        now = time.time() if now is None else now
        with self.lock:
            data = self._read()
            pairing = next((item for item in data["pairings"]
                            if (item.get("request") or {}).get("id") == request_id
                            and secrets.compare_digest(str(item.get("token_hash") or ""),
                                                       _hash(token))), None)
            if pairing is None or float(pairing.get("expires_at") or 0) <= now:
                return "expired", None
            state = str(pairing.get("state") or "expired")
            if state != "approved" or not claim:
                return state, None
            session_token = secrets.token_urlsafe(32)
            session_id = secrets.token_hex(12)
            request = pairing.get("request") or {}
            session = {
                "id": session_id, "token_hash": _hash(session_token),
                "created_at": _now_iso(now), "last_seen": _now_iso(now),
                "display_name": request.get("display_name") or "Mobile Companion",
                "revoked": False, "capabilities": list(DEFAULT_CAPABILITIES),
            }
            data["sessions"].append(session)
            pairing["state"] = "claimed"
            self._write(data)
            return "approved", {"token": session_token, "session": session}

    def authenticate(self, token: str, *, now: float | None = None) -> SessionGrant | None:
        if not token:
            return None
        now = time.time() if now is None else now
        with self.lock:
            data = self._read()
            session = next((item for item in data["sessions"]
                            if secrets.compare_digest(str(item.get("token_hash") or ""),
                                                      _hash(token))), None)
            if session is None or session.get("revoked"):
                return None
            session["last_seen"] = _now_iso(now)
            self._write(data)
        return SessionGrant(str(session["id"]), str(session["display_name"]),
                            tuple(session.get("capabilities") or ()))

    def sessions(self) -> list[dict[str, Any]]:
        with self.lock:
            data = self._read()
        return [{key: item.get(key) for key in
                 ("id", "display_name", "created_at", "last_seen", "revoked", "capabilities")}
                for item in data["sessions"]]

    def revoke(self, session_id: str) -> bool:
        with self.lock:
            data = self._read()
            session = next((item for item in data["sessions"] if item.get("id") == session_id), None)
            if session is None:
                return False
            session["revoked"] = True
            self._write(data)
            return True
