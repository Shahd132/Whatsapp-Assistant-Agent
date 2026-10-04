"""contacts.json (project root) maps a name to a phone number or a full chat id."""
import json
import re
from pathlib import Path

CONTACTS_FILE = Path(__file__).resolve().parent.parent / "contacts.json"


def load() -> dict[str, str]:
    try:
        data = json.loads(CONTACTS_FILE.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()}
    except (OSError, ValueError, AttributeError):
        return {}


def names() -> list[str]:
    return list(load().keys())


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _same_number(a: str, b: str) -> bool:
    # "01012345678" and "201012345678" are the same line: compare by suffix
    return bool(a and b) and min(len(a), len(b)) >= 9 and (a.endswith(b) or b.endswith(a))


def name_for(chat_id: str, number: str | None = None) -> str | None:
    """Reverse lookup: which contacts.json name does this chat belong to?"""
    base = chat_id.split("@")[0]
    for name, value in load().items():
        value = value.strip()
        if "@" in value:
            if value == chat_id or value.split("@")[0] == base:
                return name
        else:
            d = _digits(value)
            if _same_number(d, _digits(base)) or _same_number(d, _digits(number or "")):
                return name
    return None
