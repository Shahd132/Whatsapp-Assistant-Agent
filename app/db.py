"""SQLite store for held replies and the audit log (data/assistant.db)."""
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "assistant.db"


@contextmanager
def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with _db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS held (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, chat_id TEXT,
            incoming TEXT, reply TEXT, status TEXT DEFAULT 'pending')""")
        c.execute("""CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, target TEXT)""")


def add_held(chat_id: str, incoming: str, reply: str) -> int:
    with _db() as c:
        cur = c.execute("INSERT INTO held (ts, chat_id, incoming, reply) VALUES (?, ?, ?, ?)",
                        (time.time(), chat_id, incoming, reply))
        return cur.lastrowid


def pending() -> list[dict]:
    with _db() as c:
        rows = c.execute("SELECT * FROM held WHERE status = 'pending' ORDER BY id DESC LIMIT 50")
        return [dict(r) for r in rows]


def get(item_id: int) -> dict | None:
    with _db() as c:
        row = c.execute("SELECT * FROM held WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None


def transition(item_id: int, expected: str, new: str) -> bool:
    """Atomic status change. Moving pending -> sending first means a double
    click or a retry can never send the same reply twice."""
    with _db() as c:
        cur = c.execute("UPDATE held SET status = ? WHERE id = ? AND status = ?", (new, item_id, expected))
        return cur.rowcount == 1


def log(kind: str, target: str = "") -> None:
    with _db() as c:
        c.execute("INSERT INTO audit (ts, kind, target) VALUES (?, ?, ?)", (time.time(), kind, target))