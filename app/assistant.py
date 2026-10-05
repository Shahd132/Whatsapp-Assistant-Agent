"""Dashboard assistant: chats with the owner and acts through a few tools.

Security model: incoming chats are never put in this context, so a contact's
message can't instruct it (prompt injection). show_messages is answered by a
plain database query and the page renders the rows itself, so the model never
reads message text and listing messages costs almost no tokens.

Sending: send_message goes out immediately when "direct send" is on (the page
performs it through the normal, validated /api/send-text route); draft_message
always shows a card to review first.
"""
import json
import os
import re
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app import db
from app.controls import CAIRO, RANGE_LABELS, find_messages
from app.dashboard import _contact_names, require_auth
from app.llm import _STYLE_EXAMPLES, _get_client

router = APIRouter()
AUTH = [Depends(require_auth)]
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Mika")
_ARABIC = re.compile(r"[\u0600-\u06FF]")


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}}


TOOLS = [
    _tool("send_message", "Send a WhatsApp text to one contact right now, in the owner's voice. Use when she tells you to send, tell or message someone.",
          {"contact": {"type": "string"}, "text": {"type": "string"}}, ["contact", "text"]),
    _tool("draft_message", "Write a message for the owner to review before it is sent. Use only when she asks you to write, draft or word something, or says to check with her first.",
          {"contact": {"type": "string"}, "text": {"type": "string"}}, ["contact", "text"]),
    _tool("send_location", "Send the owner's current location pin to one contact.",
          {"contact": {"type": "string"}}, ["contact"]),
    _tool("show_messages", "Show the owner the messages people sent her and the replies sent as her. Use when she asks who messaged her, what someone sent, or to list messages. The app displays them; you never see their content.",
          {"contact": {"type": "string", "description": "Omit to include everyone."},
           "range": {"type": "string", "enum": list(RANGE_LABELS)},
           "direction": {"type": "string", "enum": ["received", "sent", "both"]}}, []),
]


def _system_prompt(names: list[str], now: datetime) -> str:
    return f"""Your name is {ASSISTANT_NAME}. You are the owner's private assistant inside her WhatsApp dashboard. Talk with her naturally and helpfully in whatever language she writes in: answer questions, help her think, help her word things. You can also act through tools.
It is {now.strftime('%A %d %B %Y, %I:%M %p')} (Cairo time).
Known contacts (the only valid recipients and message filters): {", ".join(names) or "none"}.
Match her wording to a listed name, written exactly as listed (for example "ماما", "mama" or "mom" means the listed name that is her mother). If you can't tell who she means, ask her. Never invent contacts, numbers or locations.
Tools:
- send_message: when she tells you to send, tell or message someone. It goes out immediately, so write the text the way she texts: first person, feminine forms, Egyptian Arabic unless she implies another language, short and casual, no punctuation except a final "؟" for questions. If she dictates the words, keep them.
- draft_message: only when she asks you to write, draft or word something for her to review, or says to check with her first.
- send_location: to send her current location pin.
- show_messages: when she asks who messaged her, what someone sent, or to list messages. The app shows them itself. You can't read their content, so never describe, summarise or guess what any message says.
For anything else, just answer in text. Don't call a tool for normal conversation. Reply in the language she writes in.
Voice examples for drafting:
{_STYLE_EXAMPLES}"""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[dict] = Field(default_factory=list, max_length=10)


_AR_WHEN = {"today": "النهاردة", "yesterday": "امبارح", "last_7_days": "في آخر ٧ أيام", "all": "في السجل"}


def _ar_count(n: int) -> str:
    return "رسالة واحدة" if n == 1 else "رسالتين" if n == 2 else f"{n} رسائل" if n <= 10 else f"{n} رسالة"


def _messages_reply(contact: str | None, period: str, direction: str, count: int, arabic: bool) -> str:
    if arabic:
        when = _AR_WHEN[period]
        if not count:
            return f"مفيش رسايل{' مع ' + contact if contact else ''} {when}"
        n = _ar_count(count)
        if direction == "received":
            return f"وصلك {n}{' من ' + contact if contact else ''} {when}:"
        if direction == "sent":
            return f"انتي بعتي {n}{' لـ' + contact if contact else ''} {when}:"
        return f"في {n}{' مع ' + contact if contact else ''} {when}:"
    kind = {"received": "received ", "sent": "sent ", "both": ""}[direction]
    who = f" with {contact}" if contact else ""
    if not count:
        return f"No {kind}messages{who} {RANGE_LABELS[period]}."
    return f"{count} {kind}{'message' if count == 1 else 'messages'}{who} {RANGE_LABELS[period]}:"


def handle_call(fn: str, args: dict, names: list[str], direct: bool, arabic: bool = False) -> dict:
    """Turn one tool call into a response for the page. Pure logic, no model involved."""
    known = {n.strip().lower(): n for n in names}
    raw_contact = str(args.get("contact") or "").strip()
    contact = known.get(raw_contact.lower())
    unknown = "مش لاقية الاسم ده في contacts.json." if arabic else "I couldn't find that name in contacts.json."

    if fn == "show_messages":
        if raw_contact and not contact:
            return {"reply": unknown, "action": None}
        period = args.get("range") if args.get("range") in RANGE_LABELS else "today"
        direction = args.get("direction") if args.get("direction") in ("received", "sent", "both") else "both"
        items = find_messages(contact, period, direction, 50)
        reply = _messages_reply(contact, period, direction, len(items), arabic)
        return {"reply": reply, "action": {"type": "messages", "items": items} if items else None}

    if not contact:
        return {"reply": unknown, "action": None}

    if fn in ("send_message", "draft_message"):
        text = str(args.get("text", "")).strip()
        if not text:
            return {"reply": "اكتب الرسالة ايه؟" if arabic else "What should the message say?", "action": None}
        auto = direct and fn == "send_message"
        if arabic:
            reply = f"جاري الارسال لـ{contact}…" if auto else f"مسودة لـ{contact}:"
        else:
            reply = f"Sending to {contact}…" if auto else f"Draft for {contact}:"
        return {"reply": reply, "action": {"type": "text", "contact": contact, "text": text, "auto": auto}}

    if fn == "send_location":
        if arabic:
            reply = f"جاري ارسال موقعك لـ{contact}…" if direct else f"جاهزة ابعت موقعك لـ{contact}."
        else:
            reply = f"Sending your location to {contact}…" if direct else f"Ready to send your current location to {contact}."
        return {"reply": reply, "action": {"type": "location", "contact": contact, "auto": direct}}

    return {"reply": "I can't do that one.", "action": None}


@router.post("/api/assistant", dependencies=AUTH)
def assistant(body: ChatRequest):  # plain def: runs in a thread pool
    names = _contact_names()
    history = [
        {"role": m["role"], "content": str(m.get("content", ""))[:1500]}
        for m in body.history if m.get("role") in ("user", "assistant")
    ]
    resp = _get_client().chat.completions.create(
        model=os.getenv("OPENAI_MODEL"),
        tools=TOOLS,
        temperature=0.3,
        max_tokens=600,
        messages=[{"role": "system", "content": _system_prompt(names, datetime.now(CAIRO))}, *history,
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
    arabic = bool(_ARABIC.search(body.message))
    return handle_call(call.function.name, args, names, db.direct_send_enabled(), arabic)
