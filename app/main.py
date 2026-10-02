import os
from dotenv import load_dotenv

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

from app.agent_graph import run_agent
from app.memory import add_assistant_message, add_user_message
from app.tts import synthesize_to_base64
# with the other imports at the top
from app.dashboard import router as dashboard_router
from app.assistant import router as assistant_router
load_dotenv()  # must run before app.llm reads OPENAI_API_KEY at import time

from app import db
from app.approvals import router as approvals_router

app = FastAPI()
app.include_router(dashboard_router)
app.include_router(assistant_router)
app.include_router(approvals_router)
db.init()

REPLY_WITH_VOICE = os.getenv("REPLY_WITH_VOICE", "false") == "true"
ALLOW_GROUPS = os.getenv("ALLOW_GROUPS", "false")== "true"

# held_replies: list[dict] = []


def _load_allowed_contacts() -> set[str]:
    raw = os.getenv("ALLOWED_CONTACTS", "")
    return {c.strip() for c in raw.split(",") if c.strip()}


def is_allowed(contact_id: str) -> bool:
    if contact_id.endswith("@g.us") and not ALLOW_GROUPS:
        return False

    allowed = _load_allowed_contacts()
    if not allowed:
        return True

    number = contact_id.split("@")[0]
    return number in allowed


class IncomingMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(default=None, alias="from")
    body: str = ""
    type: str = "text"           # "text" | "voice" | "image"
    media_base64: str | None = None
    mimetype: str | None = None


@app.post("/webhook")
async def webhook(msg: IncomingMessage):
    if not is_allowed(msg.from_):
        return {"action": "ignore"}

    result = run_agent(
        contact_id=msg.from_,
        message_type=msg.type,
        raw_text=msg.body,
        media_base64=msg.media_base64,
        
    )

    add_user_message(msg.from_, result["resolved_text"])

    if result["action"] == "hold":
        # held_replies.append({"from": msg.from_, "reply_text": result["reply_text"]})
        db.add_held(msg.from_, result["resolved_text"], result["reply_text"])
        return {"action": "hold", "reply_text": result["reply_text"]}

    add_assistant_message(msg.from_, result["reply_text"])
    db.log("auto_reply", msg.from_)
    response = {"action": "send", "reply_text": result["reply_text"], "reply_audio_base64": None}

    if REPLY_WITH_VOICE and msg.type == "voice":
        response["reply_audio_base64"] = await synthesize_to_base64(result["reply_text"])

    return response


# @app.get("/held")
# async def get_held_replies():
#     return held_replies


@app.get("/health")
async def health():
    return {"status": "ok"}