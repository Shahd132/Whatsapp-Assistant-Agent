"""Owner controls: auto-reply kill switch, per-contact modes, activity feed."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import contacts, db
from app.dashboard import require_auth
from app.log import log_event

router = APIRouter()
AUTH = [Depends(require_auth)]
_NAMED_KINDS = {"auto_reply", "held", "held_sent"}  # audit rows whose target is a chat id


class ToggleRequest(BaseModel):
    enabled: bool


class ModeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    mode: Literal["auto", "hold", "ignore"]


def _status() -> dict:
    return {"auto_reply": db.auto_reply_enabled(), "held": len(db.pending())}


@router.get("/api/status", dependencies=AUTH)
def status():
    return _status()


@router.post("/api/auto-reply", dependencies=AUTH)
def set_auto_reply(body: ToggleRequest):
    db.set_setting("auto_reply", "1" if body.enabled else "0")
    db.log("auto_reply_toggled", "on" if body.enabled else "off")
    log_event("auto_reply_toggled", enabled=body.enabled)
    return _status()


@router.get("/api/contact-modes", dependencies=AUTH)
def list_modes():
    modes = db.all_modes()
    return {"contacts": [{"name": n, "mode": modes.get(n.lower(), "auto")} for n in contacts.names()]}


@router.post("/api/contact-modes", dependencies=AUTH)
def change_mode(body: ModeRequest):
    canonical = {n.lower(): n for n in contacts.names()}.get(body.name.strip().lower())
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
