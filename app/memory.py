from collections import defaultdict, deque

MAX_TURNS_PER_CONTACT = 8  # 8 user+assistant exchanges = 16 messages of context

_memory: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_TURNS_PER_CONTACT * 2))


def add_user_message(contact_id: str, text: str) -> None:
    _memory[contact_id].append({"role": "user", "content": text})


def add_assistant_message(contact_id: str, text: str) -> None:
    _memory[contact_id].append({"role": "assistant", "content": text})


def get_history(contact_id: str) -> list[dict]:
    return list(_memory[contact_id])


def clear(contact_id: str) -> None:
    _memory.pop(contact_id, None)