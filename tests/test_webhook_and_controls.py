import pytest

from app import main

HEADERS = {"x-bridge-token": "bridge-secret"}


def msg(**over):
    return {"from": "201000000000@c.us", "number": "201000000000", "body": "hi", "type": "text", **over}


@pytest.fixture()
def agent(monkeypatch):
    state = {"action": "send", "hold_reason": ""}

    def fake(contact_id, message_type, raw_text, media_base64):
        return {"resolved_text": raw_text, "reply_text": "اه ماشي", **state}

    monkeypatch.setattr(main, "run_agent", fake)
    return state


def test_webhook_needs_the_bridge_token(client, agent):
    assert client.post("/webhook", json=msg()).status_code == 401
    assert client.post("/webhook", json=msg(), headers={"x-bridge-token": "wrong"}).status_code == 401


def test_normal_message_is_sent(client, agent):
    r = client.post("/webhook", json=msg(), headers=HEADERS).json()
    assert r["action"] == "send" and r["reply_text"] == "اه ماشي"


def test_allowlist_uses_the_number_resolved_by_the_bridge(client, agent, monkeypatch):
    monkeypatch.setenv("ALLOWED_CONTACTS", "201000000000")
    lid = msg(**{"from": "112257593794569@lid"})
    assert client.post("/webhook", json=lid, headers=HEADERS).json()["action"] == "send"
    stranger = msg(**{"from": "5@lid", "number": "201999999999"})
    assert client.post("/webhook", json=stranger, headers=HEADERS).json()["action"] == "ignore"


def test_groups_are_ignored_by_default(client, agent):
    assert client.post("/webhook", json=msg(**{"from": "123@g.us"}), headers=HEADERS).json()["action"] == "ignore"


def test_agent_hold_is_queued_with_name_and_reason(signed_in, agent):
    agent.update(action="hold", hold_reason="needs_owner")
    assert signed_in.post("/webhook", json=msg(), headers=HEADERS).json()["action"] == "hold"
    item = signed_in.get("/api/held").json()["items"][0]
    assert item["name"] == "Mom" and item["reason"] == "needs_owner"


def test_kill_switch_holds_everything(signed_in, agent):
    assert signed_in.post("/api/auto-reply", json={"enabled": False}).json()["auto_reply"] is False
    r = signed_in.post("/webhook", json=msg(), headers=HEADERS).json()
    assert r["action"] == "hold" and r["reason"] == "paused"
    signed_in.post("/api/auto-reply", json={"enabled": True})
    assert signed_in.post("/webhook", json=msg(), headers=HEADERS).json()["action"] == "send"


def test_contact_modes(signed_in, agent):
    assert signed_in.post("/api/contact-modes", json={"name": "mom", "mode": "hold"}).json()["name"] == "Mom"
    r = signed_in.post("/webhook", json=msg(), headers=HEADERS).json()
    assert r["action"] == "hold" and r["reason"] == "contact_mode"
    signed_in.post("/api/contact-modes", json={"name": "Mom", "mode": "ignore"})
    assert signed_in.post("/webhook", json=msg(), headers=HEADERS).json()["action"] == "ignore"


def test_unknown_contact_cannot_get_a_mode(signed_in):
    assert signed_in.post("/api/contact-modes", json={"name": "Nobody", "mode": "hold"}).status_code == 400
    assert signed_in.post("/api/contact-modes", json={"name": "Mom", "mode": "bogus"}).status_code == 422


def test_activity_feed_resolves_names(signed_in, agent):
    signed_in.post("/webhook", json=msg(), headers=HEADERS)
    first = signed_in.get("/api/audit").json()["items"][0]
    assert first["kind"] == "auto_reply" and first["name"] == "Mom"
