"""Approval queue for held replies.

The browser only ever sends an item id (and optionally edited text). The chat
id comes from the database, so this page can't be used to message arbitrary
numbers.
"""
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import contacts, db
from app.log import log_event
from app.dashboard import require_auth
from app.memory import add_assistant_message

router = APIRouter()
AUTH = [Depends(require_auth)]


class SendRequest(BaseModel):
    text: str | None = Field(default=None, max_length=4000)


@router.get("/api/held", dependencies=AUTH)
def list_held():
    items = []
    for r in db.pending():
        name = contacts.name_for(r["chat_id"], r.get("number"))
        items.append({
            "id": r["id"], "name": name, "from": name or r["chat_id"].split("@")[0],
            "incoming": r["incoming"], "reply": r["reply"], "reason": r.get("reason") or "",
        })
    return {"items": items}


@router.post("/api/held/{item_id}/send", dependencies=AUTH)
def send_held(item_id: int, body: SendRequest):
    item = db.get(item_id)
    if not item:
        raise HTTPException(404, "No such item.")
    text = (body.text if body.text is not None else item["reply"]).strip()
    if not text:
        raise HTTPException(400, "The reply is empty.")
    if not db.transition(item_id, "pending", "sending"):
        raise HTTPException(409, "Already handled.")

    try:
        r = httpx.post(
            f"{os.getenv('BRIDGE_API_URL', 'http://127.0.0.1:3001')}/send-reply",
            json={"chat_id": item["chat_id"], "text": text},
            headers={"x-bridge-token": os.getenv("BRIDGE_API_TOKEN", "")},
            timeout=30,
        )
        r.raise_for_status()
    except httpx.HTTPError:
        db.transition(item_id, "sending", "pending")  # nothing was sent: put it back
        raise HTTPException(502, "Couldn't send through the bridge. Is it running?")

    db.transition(item_id, "sending", "sent")
    db.log("held_sent", item["chat_id"])
    log_event("held_sent")
    add_assistant_message(item["chat_id"], text)  # keep the conversation memory coherent
    return {"status": "sent"}


@router.post("/api/held/{item_id}/dismiss", dependencies=AUTH)
def dismiss_held(item_id: int):
    if not db.transition(item_id, "pending", "dismissed"):
        raise HTTPException(409, "Already handled.")
    db.log("held_dismissed", str(item_id))
    return {"status": "dismissed"}