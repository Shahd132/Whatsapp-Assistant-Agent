import json
import time

import pytest


def _fix(age=0):
    return json.dumps({"lat": 30.04, "lon": 31.23, "acc": 12, "ts": time.time() - age})


def test_fresh_phone_fix_is_used_and_stale_one_is_deleted(fresh_db):
    from app import dashboard
    assert dashboard._phone_fix() is None
    fresh_db.set_setting("phone_location", _fix(age=10))
    assert dashboard._phone_fix()["lat"] == 30.04
    fresh_db.set_setting("phone_location", _fix(age=1000))
    assert dashboard._phone_fix() is None
    assert fresh_db.get_setting("phone_location") == ""          # not kept once it is stale


def test_send_location_needs_a_phone_fix(signed_in):
    r = signed_in.post("/api/send-location", json={"contact": "Mom"})
    assert r.status_code == 409 and "phone" in r.json()["detail"]


def test_location_that_is_sent_comes_from_the_phone_not_the_request(signed_in, monkeypatch):
    from app import dashboard
    sent = {}

    async def fake_send(kind, path, payload, cooldown):
        sent.update(payload)
        return {"status": "sent"}

    monkeypatch.setattr(dashboard, "_send", fake_send)
    assert signed_in.post("/api/phone-location", json={"latitude": 30.04, "longitude": 31.23, "accuracy": 12}).status_code == 200
    # a caller can't smuggle in its own coordinates: extra fields are ignored
    r = signed_in.post("/api/send-location", json={"contact": "Mom", "latitude": 1.0, "longitude": 2.0})
    assert r.json() == {"status": "sent"} and (sent["latitude"], sent["longitude"]) == (30.04, 31.23)


@pytest.mark.parametrize("body", [{"latitude": 91, "longitude": 0}, {"latitude": 0, "longitude": 181}, {"latitude": "x", "longitude": 0}])
def test_bad_coordinates_are_rejected(signed_in, body):
    assert signed_in.post("/api/phone-location", json=body).status_code == 422


def test_phone_location_requires_login(client):
    assert client.post("/api/phone-location", json={"latitude": 1, "longitude": 1}).status_code == 401
