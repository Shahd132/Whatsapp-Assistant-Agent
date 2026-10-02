"""Parse WhatsApp chat exports into (their message, your reply) pairs for style retrieval."""
import re

# "[5:33 pm, 29/09/2026] Name: text"  (iOS / copied from WhatsApp Web)
_BRACKET = re.compile(r"^\u200e?\[([^\]]+)\]\s*([^:]{1,60}):\s?(.*)$")
# "29/09/2026, 5:33 pm - Name: text"  (Android)
_ANDROID = re.compile(
    r"^\u200e?(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap]\.?[Mm]\.?)?)"
    r"\s+-\s+([^:]{1,60}):\s?(.*)$"
)
# a timestamp at the start of a line with no "Name:" after it is a system line
# ("Missed voice call", "security code changed"), never a continuation
_STAMP = re.compile(r"^\u200e?(\[|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4},?\s+\d{1,2}:\d{2})")
_SKIP = ("omitted", "<media", "<attached", "(file attached)", "deleted", "http://", "https://")
_DIGITS = re.compile(r"[0-9\u0660-\u0669]")


def parse_messages(text: str) -> list[tuple[str, str]]:
    messages: list[list[str]] = []
    for line in text.splitlines():
        m = _BRACKET.match(line) or _ANDROID.match(line)
        if m:
            messages.append([m.group(2).strip(), m.group(3).strip()])
        elif messages and line.strip() and not _STAMP.match(line):
            messages[-1][1] += " " + line.strip()  # multi-line message continues
    return [(sender, body) for sender, body in messages]


def build_pairs(messages: list[tuple[str, str]], owner: str) -> list[dict]:
    pairs, incoming, reply = [], [], []

    def flush():
        if incoming and reply:
            pairs.append({"incoming": " ".join(incoming), "reply": " ".join(reply)})
        incoming.clear()
        reply.clear()

    for sender, body in messages:
        if any(marker in body.lower() for marker in _SKIP):
            continue
        if sender == owner:
            if incoming:
                reply.append(body)
        else:
            if reply:
                flush()
            incoming.append(body)
    flush()

    # Keep short replies only, and drop any with digits: those are usually
    # facts (times, numbers) that would be stale if the model copied them.
    seen, kept = set(), []
    for p in pairs:
        key = (p["incoming"], p["reply"])
        if key in seen or not 0 < len(p["reply"]) <= 120 or len(p["incoming"]) > 300 or _DIGITS.search(p["reply"]):
            continue
        seen.add(key)
        kept.append(p)
    return kept