"""Dashboard assistant: turns an instruction into ONE proposed action.

It never sends anything itself. The page shows the proposal and the owner
presses Send, which calls the existing /api/send-text or /api/send-location.
Incoming chats are never put in this context, so a contact's message can't
instruct it (prompt injection).
"""
import json
import os

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.dashboard import _check_token, _contact_names
from app.llm import _STYLE_EXAMPLES, _get_client

router = APIRouter()

TOOLS = [
    {"type": "function", "function": {
        "name": "propose_message",
        "description": "Propose sending a WhatsApp text to one contact, written in the owner's own voice.",
        "parameters": {"type": "object", "properties": {
            "contact": {"type": "string"}, "text": {"type": "string"}},
            "required": ["contact", "text"]}}},
    {"type": "function", "function": {
        "name": "propose_location",
        "description": "Propose sending the owner's current location pin to one contact.",
        "parameters": {"type": "object", "properties": {"contact": {"type": "string"}},
                       "required": ["contact"]}}},
]


def _system_prompt(names: list[str]) -> str:
    return f"""You are the owner's private WhatsApp assistant. She types instructions; you turn them into ONE proposed action with a tool, or answer briefly when no action fits.
Known contacts (the only valid recipients): {", ".join(names) or "none"}.
Use the contact name exactly as listed. If the person isn't listed, say so and call no tool. Never invent contacts, numbers or locations.
When drafting a message, write it the way the owner texts: first person, feminine forms, Egyptian Arabic unless the instruction implies another language, short and casual, no punctuation except a final "؟" for questions. Voice examples:
{_STYLE_EXAMPLES}
You only propose; the owner confirms in the UI before anything is sent. Reply in the language the owner writes in."""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[dict] = Field(default_factory=list, max_length=10)


@router.post("/api/assistant")
def assistant(body: ChatRequest, x_dashboard_token: str = Header(default="")):  # plain def: runs in a thread pool
    _check_token(x_dashboard_token)
    names = _contact_names()
    history = [
        {"role": m["role"], "content": str(m.get("content", ""))[:1500]}
        for m in body.history if m.get("role") in ("user", "assistant")
    ]
    resp = _get_client().chat.completions.create(
        model=os.getenv("OPENAI_MODEL"),
        tools=TOOLS,
        temperature=0.3,
        messages=[{"role": "system", "content": _system_prompt(names)}, *history,
                  {"role": "user", "content": body.message}],
    )
    msg = resp.choices[0].message
    if not msg.tool_calls:
        return {"reply": (msg.content or "").strip(), "action": None}

    call = msg.tool_calls[0]
    try:
        args = json.loads(call.function.arguments)
    except ValueError:
        return {"reply": "I couldn't understand that instruction. Try rephrasing it.", "action": None}

    known = {n.strip().lower(): n for n in names}
    contact = known.get(str(args.get("contact", "")).strip().lower())
    if not contact:
        return {"reply": "I couldn't find that name in contacts.json.", "action": None}

    if call.function.name == "propose_message":
        text = str(args.get("text", "")).strip()
        if not text:
            return {"reply": "What should the message say?", "action": None}
        return {"reply": f"Draft for {contact}:", "action": {"type": "text", "contact": contact, "text": text}}
    return {"reply": f"Ready to send your current location to {contact}.",
            "action": {"type": "location", "contact": contact}}