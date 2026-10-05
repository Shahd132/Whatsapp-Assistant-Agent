"""Owner controls: auto-reply kill switch, per-contact modes, activity feed."""
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import contacts, db
from app.dashboard import require_auth
from app.log import log_event

router = APIRouter()
AUTH = [Depends(require_auth)]
_NAMED_KINDS = {"auto_reply", "held", "held_sent"}  # audit rows whose target is a chat id
CAIRO = ZoneInfo("Africa/Cairo")
RANGE_LABELS = {"today": "today", "yesterday": "yesterday", "last_7_days": "in the last 7 days", "all": "in the stored history"}


def time_bounds(label: str, now: datetime | None = None) -> tuple[float | None, float | None]:
    """(since, until) as timestamps, using Cairo midnight as the start of a day."""
    now = now or datetime.now(CAIRO)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if label == "today":
        return midnight.timestamp(), None
    if label == "yesterday":
        return (midnight - timedelta(days=1)).timestamp(), midnight.timestamp()
    if label == "last_7_days":
        return (midnight - timedelta(days=6)).timestamp(), None
    return None, None


def find_messages(contact: str | None, period: str, direction: str, limit: int = 100) -> list[dict]:
    """Plain database query: no model involved, so listing messages costs no tokens."""
    since, until = time_bounds(period)
    rows = db.query_messages(contact, since, until, {"received": "in", "sent": "out"}.get(direction), limit)
    return [{"ts": r["ts"], "direction": r["direction"], "body": r["body"], "outcome": r["outcome"],
             "name": r["name"] or (r["chat_id"].split("@")[0] if r["chat_id"] else "")} for r in rows]


class ToggleRequest(BaseModel):
    enabled: bool


class ModeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    mode: Literal["auto", "hold", "ignore"]


def _status() -> dict:
    return {"auto_reply": db.auto_reply_enabled(), "direct_send": db.direct_send_enabled(), "held": len(db.pending())}


@router.get("/api/status", dependencies=AUTH)
def status():
    return _status()


@router.post("/api/auto-reply", dependencies=AUTH)
def set_auto_reply(body: ToggleRequest):
    db.set_setting("auto_reply", "1" if body.enabled else "0")
    db.log("auto_reply_toggled", "on" if body.enabled else "off")
    log_event("auto_reply_toggled", enabled=body.enabled)
    return _status()


@router.post("/api/direct-send", dependencies=AUTH)
def set_direct_send(body: ToggleRequest):
    db.set_setting("direct_send", "1" if body.enabled else "0")
    db.log("direct_send_toggled", "on" if body.enabled else "off")
    log_event("direct_send_toggled", enabled=body.enabled)
    return _status()


@router.get("/api/messages", dependencies=AUTH)
def messages(contact: str = "", period: Literal["today", "yesterday", "last_7_days", "all"] = Query("today", alias="range"),
             direction: Literal["received", "sent", "both"] = "both", limit: int = 100):
    name = None
    if contact:
        name = contacts.canonical(contact)
        if not name:
            raise HTTPException(400, "Unknown contact.")
    return {"items": find_messages(name, period, direction, limit)}


@router.get("/api/contact-modes", dependencies=AUTH)
def list_modes():
    modes = db.all_modes()
    return {"contacts": [{"name": n, "mode": modes.get(n.lower(), "auto")} for n in contacts.names()]}


@router.post("/api/contact-modes", dependencies=AUTH)
def change_mode(body: ModeRequest):
    canonical = contacts.canonical(body.name)
    if not canonical:
        raise HTTPException(400, "Unknown contact. Add the name to contacts.json.")
    db.set_mode(canonical, body.mode)
    db.log("mode_changed", f"{canonical}: {body.mode}")
    log_event("mode_changed", mode=body.mode)
    return {"name": canonical, "mode": body.mode}


@router.get("/api/audit", dependencies=AUTH)
def audit(limit: int = 50):
    limit = max(1, min(limit, 200))
    items = []
    for r in db.recent_audit(limit):
        name = contacts.name_for(r["target"]) if r["kind"] in _NAMED_KINDS and r["target"] else None
        items.append({"ts": r["ts"], "kind": r["kind"], "target": "" if name else r["target"], "name": name})
    return {"items": items}
