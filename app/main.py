import hmac
import os

from dotenv import load_dotenv

load_dotenv()  # first, so every module below sees the .env values (USER_NAME, tokens...)

from fastapi import FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from app import db
from app.agent_graph import run_agent
from app.approvals import router as approvals_router
from app.assistant import router as assistant_router
from app.contacts import name_for
from app.controls import router as controls_router
from app.dashboard import router as dashboard_router
from app.log import anon, log_event
from app.memory import add_assistant_message, add_user_message
from app.tts import synthesize_to_base64

app = FastAPI()
app.include_router(dashboard_router)
app.include_router(assistant_router)
app.include_router(approvals_router)
app.include_router(controls_router)
db.init()

REPLY_WITH_VOICE = os.getenv("REPLY_WITH_VOICE", "false") == "true"
ALLOW_GROUPS = os.getenv("ALLOW_GROUPS", "false") == "true"


def _load_allowed_contacts() -> set[str]:
    raw = os.getenv("ALLOWED_CONTACTS", "")
    return {c.strip() for c in raw.split(",") if c.strip()}


def is_allowed(contact_id: str, number: str | None = None) -> bool:
    if contact_id.endswith("@g.us") and not ALLOW_GROUPS:
        return False

    allowed = _load_allowed_contacts()
    if not allowed:
        return True

    # The bridge resolves opaque "@lid" ids to a real phone number and sends it
    # as `number`; fall back to the id itself for plain "@c.us" contacts.
    return (number or contact_id.split("@")[0]).strip() in allowed


class IncomingMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(default=None, alias="from")
    body: str = ""
    type: str = "text"           # "text" | "voice" | "image"
    media_base64: str | None = None
    mimetype: str | None = None
    number: str | None = None    # phone number resolved by the bridge (for @lid contacts)


@app.post("/webhook")
async def webhook(msg: IncomingMessage, x_bridge_token: str = Header(default="")):
    # Only the local bridge may call this. Without it, anyone who can reach the
    # port (or a tunnel pointing at it) could make the agent reply as you.
    expected = os.getenv("BRIDGE_API_TOKEN", "")
    if not expected or not hmac.compare_digest(x_bridge_token.encode(), expected.encode()):
        raise HTTPException(401, "unauthorized")

    if not is_allowed(msg.from_, msg.number):
        return {"action": "ignore"}

    name = name_for(msg.from_, msg.number)
    mode = db.get_mode(name)
    if mode == "ignore":
        return {"action": "ignore"}

    # run_agent is blocking (LLM, Whisper, BLIP): keep it off the event loop
    result = await run_in_threadpool(
        run_agent,
        contact_id=msg.from_,
        message_type=msg.type,
        raw_text=msg.body,
        media_base64=msg.media_base64,
    )

    add_user_message(msg.from_, result["resolved_text"])

    action, reason = result["action"], result.get("hold_reason", "")
    if action == "send" and not db.auto_reply_enabled():
        action, reason = "hold", "paused"          # global kill switch
    elif action == "send" and mode == "hold":
        action, reason = "hold", "contact_mode"    # this contact is always approved by hand

    if action == "hold":
        db.add_held(msg.from_, result["resolved_text"], result["reply_text"], reason=reason, number=msg.number)
        db.log("held", msg.from_)
        log_event("held", chat=anon(msg.from_), reason=reason)
        return {"action": "hold", "reply_text": result["reply_text"], "reason": reason}

    add_assistant_message(msg.from_, result["reply_text"])
    db.log("auto_reply", msg.from_)
    log_event("auto_reply", chat=anon(msg.from_))
    response = {"action": "send", "reply_text": result["reply_text"], "reply_audio_base64": None}

    if REPLY_WITH_VOICE and msg.type == "voice":
        response["reply_audio_base64"] = await synthesize_to_base64(result["reply_text"])

    return response


@app.get("/health")
async def health():
    return {"status": "ok"}
