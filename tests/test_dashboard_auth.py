import pytest

PROTECTED = [("get", "/api/held"), ("get", "/api/status"), ("get", "/api/audit"),
             ("get", "/api/contact-modes"), ("get", "/api/contacts"), ("get", "/api/session"),
             ("post", "/api/transcribe"), ("post", "/api/assistant"), ("post", "/api/auto-reply")]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_api_requires_login(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_page_itself_is_public_and_not_cached(client):
    r = client.get("/dashboard")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert "test-password" not in r.text


def test_login_sets_a_hardened_cookie(client):
    r = client.post("/api/login", json={"password": "test-password"})
    cookie = r.headers["set-cookie"].lower()
    assert r.status_code == 200 and "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/session").status_code == 200


def test_wrong_password_then_per_ip_lockout(client):
    for _ in range(5):
        assert client.post("/api/login", json={"password": "nope"}).status_code == 401
    assert client.post("/api/login", json={"password": "test-password"}).status_code == 429


def test_forged_and_expired_cookies_are_rejected(client):
    client.cookies.set("dash_session", "9999999999.deadbeef")
    assert client.get("/api/session").status_code == 401
    client.cookies.set("dash_session", "1.deadbeef")
    assert client.get("/api/session").status_code == 401


def test_remember_off_gives_a_session_cookie(client):
    r = client.post("/api/login", json={"password": "test-password", "remember": False})
    assert "max-age" not in r.headers["set-cookie"].lower()


def test_logout_clears_the_session(signed_in):
    signed_in.post("/api/logout")
    assert signed_in.get("/api/session").status_code == 401


def test_transcribe_validates_input(signed_in):
    assert signed_in.post("/api/transcribe?lang=ar", content=b"abc").json() == {"text": "heard 3 bytes"}
    assert signed_in.post("/api/transcribe?lang=fr", content=b"abc").status_code == 400
    assert signed_in.post("/api/transcribe?lang=ar", content=b"").status_code == 400
