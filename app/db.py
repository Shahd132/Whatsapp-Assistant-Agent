"""SQLite store (data/assistant.db): held replies, audit log, conversation
memory, per-contact modes and settings."""
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


def _add_column(c, table: str, column: str, ddl: str) -> None:
    """Tiny migration helper so an existing assistant.db keeps working."""
    if column not in {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init() -> None:
    with _db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS held (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, chat_id TEXT,
            incoming TEXT, reply TEXT, status TEXT DEFAULT 'pending')""")
        _add_column(c, "held", "reason", "TEXT DEFAULT ''")
        _add_column(c, "held", "number", "TEXT DEFAULT ''")
        c.execute("""CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, target TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, chat_id TEXT, role TEXT, content TEXT)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages (chat_id, id)")
        c.execute("CREATE TABLE IF NOT EXISTS contact_modes (name TEXT PRIMARY KEY, mode TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")


# ---- held replies ----

def add_held(chat_id: str, incoming: str, reply: str, reason: str = "", number: str | None = None) -> int:
    with _db() as c:
        cur = c.execute(
            "INSERT INTO held (ts, chat_id, incoming, reply, reason, number) VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), chat_id, incoming, reply, reason, number or ""))
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


# ---- audit ----

def log(kind: str, target: str = "") -> None:
    with _db() as c:
        c.execute("INSERT INTO audit (ts, kind, target) VALUES (?, ?, ?)", (time.time(), kind, target))


def recent_audit(limit: int = 50) -> list[dict]:
    with _db() as c:
        rows = c.execute("SELECT ts, kind, target FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]


# ---- conversation memory (survives restarts; only the last `keep` messages per chat) ----

def add_message(chat_id: str, role: str, content: str, keep: int = 16) -> None:
    with _db() as c:
        c.execute("INSERT INTO messages (ts, chat_id, role, content) VALUES (?, ?, ?, ?)",
                  (time.time(), chat_id, role, content))
        c.execute("""DELETE FROM messages WHERE chat_id = ? AND id NOT IN
                     (SELECT id FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?)""",
                  (chat_id, chat_id, keep))


def get_messages(chat_id: str, limit: int = 16) -> list[dict]:
    with _db() as c:
        rows = c.execute("SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
                         (chat_id, limit)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_messages(chat_id: str) -> None:
    with _db() as c:
        c.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))


# ---- per-contact modes: "auto" (default) | "hold" (always ask me) | "ignore" ----

MODES = ("auto", "hold", "ignore")


def set_mode(name: str, mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"bad mode: {mode}")
    with _db() as c:
        if mode == "auto":
            c.execute("DELETE FROM contact_modes WHERE name = ?", (name.strip().lower(),))
        else:
            c.execute("INSERT INTO contact_modes (name, mode) VALUES (?, ?) "
                      "ON CONFLICT(name) DO UPDATE SET mode = excluded.mode", (name.strip().lower(), mode))


def get_mode(name: str | None) -> str:
    if not name:
        return "auto"
    with _db() as c:
        row = c.execute("SELECT mode FROM contact_modes WHERE name = ?", (name.strip().lower(),)).fetchone()
        return row["mode"] if row else "auto"


def all_modes() -> dict[str, str]:
    with _db() as c:
        return {r["name"]: r["mode"] for r in c.execute("SELECT name, mode FROM contact_modes")}


# ---- settings (global kill switch) ----

def get_setting(key: str, default: str = "") -> str:
    with _db() as c:
        row = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with _db() as c:
        c.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                  "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def auto_reply_enabled() -> bool:
    return get_setting("auto_reply", "1") == "1"
