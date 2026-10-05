def test_transition_is_atomic(fresh_db):
    item = fresh_db.add_held("1@c.us", "hi", "hello", reason="needs_owner")
    assert fresh_db.transition(item, "pending", "sending") is True
    assert fresh_db.transition(item, "pending", "sending") is False   # a double click can't send twice
    assert fresh_db.get(item)["status"] == "sending"


def test_pending_only_lists_pending_and_keeps_reason(fresh_db):
    a = fresh_db.add_held("1@c.us", "a", "r", reason="paused")
    b = fresh_db.add_held("2@c.us", "b", "r")
    fresh_db.transition(b, "pending", "dismissed")
    rows = fresh_db.pending()
    assert [r["id"] for r in rows] == [a] and rows[0]["reason"] == "paused"


def test_memory_keeps_only_the_last_messages_in_order(fresh_db):
    for i in range(10):
        fresh_db.add_message("c1", "user", f"m{i}", keep=4)
    fresh_db.add_message("c2", "user", "other", keep=4)
    assert [m["content"] for m in fresh_db.get_messages("c1")] == ["m6", "m7", "m8", "m9"]
    assert len(fresh_db.get_messages("c2")) == 1


def test_contact_modes(fresh_db):
    assert fresh_db.get_mode("Mom") == "auto" and fresh_db.get_mode(None) == "auto"
    fresh_db.set_mode("Mom", "hold")
    assert fresh_db.get_mode("mom") == "hold"          # case-insensitive
    fresh_db.set_mode("Mom", "auto")
    assert fresh_db.all_modes() == {}


def test_kill_switch_defaults_to_on(fresh_db):
    assert fresh_db.auto_reply_enabled() is True
    fresh_db.set_setting("auto_reply", "0")
    assert fresh_db.auto_reply_enabled() is False


def test_old_database_is_migrated(tmp_path, monkeypatch):
    import sqlite3

    from app import db
    path = tmp_path / "old.db"
    sqlite3.connect(path).execute(
        "CREATE TABLE held (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, chat_id TEXT, incoming TEXT, reply TEXT, status TEXT DEFAULT 'pending')"
    ).connection.commit()
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init()
    assert db.get(db.add_held("1@c.us", "a", "b", reason="x"))["reason"] == "x"


def test_message_log_filters_and_order(fresh_db):
    fresh_db.log_message("1@c.us", "Mom", "in", "هتيجي؟", "replied")
    fresh_db.log_message("1@c.us", "Mom", "out", "ايوة", "auto")
    fresh_db.log_message("2@c.us", "Dad", "in", "hi", "held")
    assert [m["body"] for m in fresh_db.query_messages()] == ["hi", "ايوة", "هتيجي؟"]          # newest first
    assert [m["body"] for m in fresh_db.query_messages(name="mom")] == ["ايوة", "هتيجي؟"]      # case-insensitive
    assert [m["body"] for m in fresh_db.query_messages(direction="in", name="Mom")] == ["هتيجي؟"]
    assert fresh_db.query_messages(since=9_999_999_999) == []


def test_message_log_time_window_and_purge(fresh_db):
    import time
    fresh_db.log_message("1@c.us", "Mom", "in", "old", "replied")
    with fresh_db._db() as c:
        c.execute("UPDATE message_log SET ts = ?", (time.time() - 40 * 86400,))
    fresh_db.log_message("1@c.us", "Mom", "in", "new", "replied")
    assert [m["body"] for m in fresh_db.query_messages(since=time.time() - 86400)] == ["new"]
    assert fresh_db.purge_messages(days=30) == 1
    assert [m["body"] for m in fresh_db.query_messages()] == ["new"]


def test_direct_send_defaults_to_on(fresh_db):
    assert fresh_db.direct_send_enabled() is True
    fresh_db.set_setting("direct_send", "0")
    assert fresh_db.direct_send_enabled() is False
