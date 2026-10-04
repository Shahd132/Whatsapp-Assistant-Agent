"""Owner-only dashboard: send a message or your GPS location to a named contact.

Put this file and dashboard.html together in app/. Names come from
contacts.json in the project root.

Auth: you type DASHBOARD_PASSWORD (from .env; the old name DASHBOARD_TOKEN
still works) once on the login screen. The server checks it and sets a signed,
HttpOnly, SameSite=Strict cookie. The password itself is never sent to the page
or stored in the browser. Changing it in .env signs every device out.

Env vars are read when a request arrives (not at import time) because main.py
calls load_dotenv() late.
"""
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app import contacts as contacts_store
from app.log import log_event
from app.stt import transcribe_bytes

router = APIRouter()

PAGE = Path(__file__).with_name("dashboard.html")

SESSION_COOKIE = "dash_session"
SESSION_SECONDS = 30 * 24 * 3600   # "keep me signed in"
SHORT_SESSION_SECONDS = 12 * 3600  # otherwise: ends when the browser closes, or after 12 h
LOGIN_WINDOW = 300      # seconds
LOGIN_MAX_FAILS = 5     # per IP, per window
MAX_AUDIO_BYTES = 10 * 1024 * 1024

_last_send: dict[str, float] = {}
_failed_logins: dict[str, list[float]] = {}


# ---------------------------------------------------------------- auth ----

def _client_ip(request: Request) -> str:
    # Behind a tunnel every request comes from localhost, so the real IP is in a
    # header. Those headers can be forged when NOT behind a proxy, so they are
    # only trusted when you opt in with TRUST_PROXY=true in .env.
    if os.getenv("TRUST_PROXY", "false").lower() == "true":
        fwd = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "")
        fwd = fwd.split(",")[0].strip()
        if fwd:
            return fwd
    return request.client.host if request.client else "unknown"


def _is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.split(",")[0].strip() == "https"


def _password() -> str:
    return os.getenv("DASHBOARD_PASSWORD") or os.getenv("DASHBOARD_TOKEN", "")


def _session_key() -> bytes:
    return hashlib.sha256(b"dashboard-session:" + _password().encode()).digest()


def _sign(expires: int) -> str:
    sig = hmac.new(_session_key(), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def _cookie_valid(value: str) -> bool:
    try:
        expires_s, sig = value.split(".", 1)
        expires = int(expires_s)
    except ValueError:
        return False
    if expires < time.time():
        return False
    good = hmac.new(_session_key(), expires_s.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good)


def require_auth(request: Request) -> None:
    """FastAPI dependency: use as dependencies=[Depends(require_auth)]."""
    if not _password():
        raise HTTPException(503, "DASHBOARD_PASSWORD is not set in .env.")
    if not _cookie_valid(request.cookies.get(SESSION_COOKIE, "")):
        raise HTTPException(401, "Please sign in.")


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    remember: bool = True


@router.post("/api/login")
def login(body: LoginRequest, request: Request, response: Response):
    expected = _password()
    if not expected:
        raise HTTPException(503, "DASHBOARD_PASSWORD is not set in .env.")

    ip, now = _client_ip(request), time.time()
    attempts = [t for t in _failed_logins.get(ip, []) if now - t < LOGIN_WINDOW]
    if len(attempts) >= LOGIN_MAX_FAILS:
        _failed_logins[ip] = attempts
        raise HTTPException(429, "Too many wrong attempts. Try again in 5 minutes.")

    if not hmac.compare_digest(body.password.encode(), expected.encode()):
        attempts.append(now)
        _failed_logins[ip] = attempts
        raise HTTPException(401, "Wrong password.")

    _failed_logins.pop(ip, None)
    lifetime = SESSION_SECONDS if body.remember else SHORT_SESSION_SECONDS
    response.set_cookie(
        SESSION_COOKIE, _sign(int(now) + lifetime),
        max_age=lifetime if body.remember else None, httponly=True, samesite="strict",
        secure=_is_https(request), path="/",
    )
    return {"status": "ok"}


@router.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "ok"}


@router.get("/api/session", dependencies=[Depends(require_auth)])
def session():
    return {"status": "ok"}


# ------------------------------------------------------------ contacts ----

class LocationRequest(BaseModel):
    contact: str = Field(min_length=1, max_length=60)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = None


class TextRequest(BaseModel):
    contact: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=4000)


def _contact_names() -> list[str]:
    return contacts_store.names()


async def _send(kind: str, path: str, payload: dict, cooldown: float) -> dict:
    known = {n.strip().lower() for n in _contact_names()}
    if payload["contact"].strip().lower() not in known:
        raise HTTPException(400, "Unknown contact. Add the name to contacts.json.")
    if time.time() - _last_send.get(kind, 0.0) < cooldown:
        raise HTTPException(429, "Just sent one. Wait a few seconds.")

    bridge_url = os.getenv("BRIDGE_API_URL", "http://127.0.0.1:3001")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{bridge_url}{path}",
                json=payload,
                headers={"x-bridge-token": os.getenv("BRIDGE_API_TOKEN", "")},
            )
    except httpx.HTTPError:
        raise HTTPException(502, "Can't reach the WhatsApp bridge. Is it running?")

    if r.status_code != 200:
        raise HTTPException(502, f"The bridge could not send it ({r.status_code}): {r.text[:120]}")

    _last_send[kind] = time.time()
    log_event("dashboard_send", kind=kind)  # no message text, name or coordinates in logs
    return {"status": "sent"}


# --------------------------------------------------------------- routes ----

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    # The page itself contains no secrets; every /api/* call needs the cookie.
    return HTMLResponse(PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/api/contacts", dependencies=[Depends(require_auth)])
async def contacts():
    return {"contacts": _contact_names()}


@router.post("/api/send-text", dependencies=[Depends(require_auth)])
async def send_text(body: TextRequest):
    return await _send("text", "/send-text", body.model_dump(), cooldown=3)


@router.post("/api/send-location", dependencies=[Depends(require_auth)])
async def send_location(body: LocationRequest):
    return await _send("location", "/send-location", body.model_dump(), cooldown=20)


@router.post("/api/transcribe", dependencies=[Depends(require_auth)])
async def transcribe(request: Request, lang: str = "ar"):
    """Raw audio bytes in the body (whatever the browser's MediaRecorder made).
    Returns text only: the page puts it in the input box and nothing is sent."""
    if lang not in ("ar", "en"):
        raise HTTPException(400, "Language must be ar or en.")
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError:
        declared = 0
    if declared > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Recording is too long.")

    audio = await request.body()
    if not audio:
        raise HTTPException(400, "No audio received.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Recording is too long.")

    try:
        # Whisper is CPU-heavy and blocking: keep it off the event loop.
        text = await run_in_threadpool(
            transcribe_bytes, audio, lang, os.getenv("DASHBOARD_WHISPER_SIZE") or None, True
        )
    except Exception as err:
        log_event("transcribe_failed", level="error", error=type(err).__name__)
        raise HTTPException(422, "Couldn't read that recording. Try again.")
    return {"text": text}
