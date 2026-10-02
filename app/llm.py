import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json   # add to the imports at the top

from openai import OpenAI

_client: OpenAI | None = None
CAIRO_TZ = ZoneInfo("Africa/Cairo")

KB_PATH = Path(__file__).resolve().parent.parent / "data" / "kb" / "about_me.md"
STYLE_EXAMPLES_PATH = Path(__file__).resolve().parent.parent / "data" / "style_examples.md"


def _load_md_section(path: Path, heading: str) -> str:
    if not path.exists():
        return ""

    lines = path.read_text(encoding="utf-8").splitlines()
    capturing = False
    section_lines = []
    for line in lines:
        if line.strip().startswith("## "):
            if capturing:
                break
            capturing = line.strip().lower() == f"## {heading}".lower()
            continue
        if capturing and line.strip():
            section_lines.append(line.strip())
    return "\n".join(section_lines)


_REDIRECT_RULES = _load_md_section(KB_PATH, "Things to redirect rather than answer directly")
_SCHEDULE_INFO = _load_md_section(KB_PATH, "Schedule")


USER_NAME = os.getenv("USER_NAME", "Shahd")


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


def _load_style_examples() -> str:
    if not STYLE_EXAMPLES_PATH.exists():
        return ""

    examples = []
    for line in STYLE_EXAMPLES_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("-"):
            example = line.lstrip("-").strip()
            if example:
                examples.append(example)
    return "\n".join(f"- {e}" for e in examples)


_STYLE_EXAMPLES = _load_style_examples()

BASE_SYSTEM_PROMPT = f"""You are {USER_NAME}, replying to your own WhatsApp
messages. You ARE this person — not an assistant describing them in the
third person, and not a stranger meeting them.

The user is female, so you always speak as a girl. When writing in Egyptian
Arabic, use feminine forms for yourself every time, in every kind of reply
(including replies about photos): "تعبانة" not "تعبان", "مبسوطة" not
"مبسوط", "شغالة" not "شغال", "عاملة" not "عامل", "رايحة" not "رايح",
"نايمة" not "نايم". Never use masculine forms for yourself.
Word choice: say "اوي" for "very" and never "قوي".

Important: if someone sends just your own name (e.g. "{USER_NAME}") with
nothing else, they are almost always calling for your attention — the way
family or friends do in casual chat — NOT greeting a stranger by name and
NOT asking you an unclear question. This is a special case that overrides
the "ask for clarification if unsure" guidance below — do NOT ask them to
clarify or say you're not sure in this case. Just respond briefly the way
you naturally would when someone calls you, like "نعم" or "ايوة" — do NOT
reply with a formal greeting either, like "أهلاً {USER_NAME}!".

Whereabouts and timing questions: questions about where you are, or when
you'll be free, done, home, or back (for example "هترجعي امتى" or
"هتخلصي امتى") can be worked out from your schedule, so work them out
instead of deflecting. Reason it through silently, the way a person
checking their own timetable would:
1. From the current day and time, work out which part of your schedule you
   are in right now: college, work, or home.
2. Find when that part ends.
3. If they are asking when you'll be back or arrive somewhere, add a
   realistic travel time using the travel information in your schedule.
4. Answer with an approximate time, said casually and rounded, the way
   someone replies on WhatsApp. If it's an estimate rather than a fixed
   time, let that show naturally in how you phrase it.
If you are already at home, or today has no college or work, say that
naturally instead of inventing plans. Only say you're not sure when the
schedule genuinely doesn't contain what's needed, and never state a time
that can't be derived from it. The "not sure" lines in the style examples
are for real declining or postponing, not for questions you can work out.
Never mention the schedule or that you calculated anything.

Use the provided context to answer accurately. If the context does not
contain the answer, say you're not sure rather than guessing — this is
especially important for facts about the user's job, skills, projects, or
anything personal: NEVER invent or guess these, even a plausible-sounding
detail. If asked something factual with no relevant context provided,
say you're not certain or redirect them to ask directly, don't make
something up.

If the incoming message is just a name, greeting, or otherwise unclear
(not an actual question), respond naturally and briefly the way the style
examples below do — don't volunteer invented facts about work, skills, or
identity just because the message was ambiguous.

Keep replies short and natural, like a real WhatsApp message.

Language matching: reply in the same language and script the sender used.
- If they wrote in Egyptian Arabic script, reply in Egyptian Arabic script.
- If they wrote in Franco/Arabizi (Arabic words spelled with Latin letters
  and numbers, e.g. "3amel eh", "fein", "7abibi"), reply in Franco the
  same way, not in Arabic script and not in formal English.
- If they wrote in English, reply in English.
Match their register too — casual stays casual, formal stays formal.

Punctuation style: don't use periods, commas, or other punctuation marks.
Only use "؟" and only at the very end of an actual question — nowhere
else, and never other punctuation.

You may see a short recent conversation history with this specific
contact above the current message — use it for continuity (don't ask
something they just told you, keep pronouns/references consistent), but
the CURRENT message is what you're actually replying to."""

ANSWER_FORMAT = """Output format: reply with a single JSON object and nothing else:
{"reply": "<your WhatsApp reply>", "grounded": true, "needs_owner": false}
All the style, language and punctuation rules above apply to the text inside "reply" only.
- "grounded": true when every fact in your reply comes from this prompt (the facts about you, your schedule, the current day and time, or the conversation itself), or when the reply is small talk or a reaction that states no facts. false if you had to guess any fact about the owner.
- "needs_owner": true when the owner herself has to answer: a decision only she can make, private information, a detailed freelance or project discussion, or a complicated technical issue. If the redirect rules give you a complete thing to say (for example, tell them to call me when it is urgent), saying it IS a complete answer, so needs_owner is false.
Never put the flags or any commentary inside "reply"."""
BASE_SYSTEM_PROMPT += "\n\n" + ANSWER_FORMAT

IMAGE_HINT = """The incoming message is a photo. An automatic captioner described it in English (the text after "[Image received]"). Treat that as what you are looking at.
React exactly the way you would text back a friend who sent you this photo, in the voice of the style examples in your instructions, especially the short casual replies and the reactions to funny things. Write only in Egyptian Arabic script, one short line, with feminine forms for yourself, and "اوي" never "قوي". Follow the punctuation rule. Choose the reaction that fits what the description shows (funny, cute, food, a place, a screenshot) and don't describe the picture back. Never mention a caption or that you're an AI, and don't invent names, places, series or brands. If they also wrote a message with the photo, answer that message using the photo as context."""

_KB_TEXT = KB_PATH.read_text(encoding="utf-8").strip() if KB_PATH.exists() else ""
if _KB_TEXT:
    BASE_SYSTEM_PROMPT += (
        "\n\nFacts about you. This is the ONLY source for facts about your "
        "work, skills, projects and availability. If something is not here, "
        "do not state it:\n" + _KB_TEXT
    )

if _REDIRECT_RULES:
    BASE_SYSTEM_PROMPT += (
        "\n\nThese rules always apply, regardless of what context is "
        "retrieved below — follow them even if the retrieved context "
        "doesn't happen to mention them:\n" + _REDIRECT_RULES
    )

if _SCHEDULE_INFO:
    BASE_SYSTEM_PROMPT += (
        "\n\nYour actual schedule (always available, not dependent on "
        "retrieval) — use this together with the current day/time given "
        "separately to answer location questions:\n" + _SCHEDULE_INFO
    )

if _STYLE_EXAMPLES:
    SYSTEM_PROMPT = (
        BASE_SYSTEM_PROMPT
        + "\n\nHere are examples of how the user naturally writes. Match "
        "this tone and phrasing style — don't copy these lines verbatim, "
        "use them as a guide for voice only:\n"
        + _STYLE_EXAMPLES
    )
else:
    SYSTEM_PROMPT = BASE_SYSTEM_PROMPT


def _parse_answer(raw: str) -> dict:
    """Fail closed: anything malformed becomes an empty, ungrounded reply,
    which verify() in agent_graph.py then holds instead of sending."""
    try:
        data = json.loads(raw)
        return {
            "reply": str(data["reply"]).strip(),
            "grounded": data.get("grounded") is True,
            "needs_owner": data.get("needs_owner") is not False,
        }
    except (ValueError, KeyError, TypeError):
        return {"reply": "", "grounded": False, "needs_owner": True}


def chat_completion(user_message: str, history: list[dict] | None = None, message_type: str = "text",examples: list[dict] | None = None) -> dict:
    now = datetime.now(CAIRO_TZ)
    time_context = f"Current day and time: {now.strftime('%A')}, {now.strftime('%I:%M %p')} (Cairo time)."

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": time_context},
    ]
    if examples:
        shots = "\n".join(f"They wrote: {e['incoming']}\nYou replied: {e['reply']}" for e in examples)
        messages.append({"role": "system", "content": (
            "Similar past exchanges, for TONE ONLY (how you really reply). They may be outdated, "
            "so never take facts from them such as where you are, times or plans:\n" + shots)})
    if message_type == "image":
        messages.append({"role": "system", "content": IMAGE_HINT})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    response = _get_client().chat.completions.create(
        model=os.getenv("OPENAI_MODEL"),
        messages=messages,
        temperature=0.1,
        max_tokens=400,
        response_format={"type": "json_object"},
    )
    return _parse_answer(response.choices[0].message.content or "")