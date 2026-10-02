"""Owner-only dashboard: send a message or your GPS location to a named contact.

Put this file and dashboard.html together in app/. Names come from
contacts.json in the project root. Env vars are read when a request arrives
(not at import time) because main.py calls load_dotenv() late.
"""
import hmac
import json
import os
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

router = APIRouter()

PAGE = Path(__file__).with_name("dashboard.html")
CONTACTS_FILE = Path(__file__).resolve().parent.parent / "contacts.json"
_last_send: dict[str, float] = {}
_failed_attempts: list[float] = []


class LocationRequest(BaseModel):
    contact: str = Field(min_length=1, max_length=60)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = None


class TextRequest(BaseModel):
    contact: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=4000)


def _contact_names() -> list[str]:
    try:
        return list(json.loads(CONTACTS_FILE.read_text(encoding="utf-8")).keys())
    except (OSError, ValueError):
        return []


def _check_token(token: str) -> None:
    now = time.time()
    _failed_attempts[:] = [t for t in _failed_attempts if now - t < 300]
    if len(_failed_attempts) >= 5:
        raise HTTPException(429, "Too many wrong tokens. Try again in 5 minutes.")

    expected = os.getenv("DASHBOARD_TOKEN", "")
    if not expected or not hmac.compare_digest(token.encode(), expected.encode()):
        _failed_attempts.append(now)
        raise HTTPException(401, "Wrong access token.")


async def _send(kind: str, path: str, payload: dict, token: str, cooldown: float) -> dict:
    _check_token(token)

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
    print(f"[{kind}] sent to {payload['contact']!r}")  # no message text or coordinates in logs
    return {"status": "sent"}


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/api/contacts")
async def contacts(x_dashboard_token: str = Header(default="")):
    _check_token(x_dashboard_token)
    return {"contacts": _contact_names()}


@router.post("/api/send-text")
async def send_text(body: TextRequest, x_dashboard_token: str = Header(default="")):
    return await _send("text", "/send-text", body.model_dump(), x_dashboard_token, cooldown=3)


@router.post("/api/send-location")
async def send_location(body: LocationRequest, x_dashboard_token: str = Header(default="")):
    return await _send("location", "/send-location", body.model_dump(), x_dashboard_token, cooldown=20)