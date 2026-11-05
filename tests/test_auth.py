import pytest

from app import auth
from app.config import settings


@pytest.fixture()
def secured(monkeypatch, client):
    monkeypatch.setattr(settings, "app_password", "correct horse battery")
    monkeypatch.setattr(settings, "secret_key", "x" * 40)
    monkeypatch.setattr(settings, "api_token", "tok-123")
    auth._fails.clear()
    client.cookies.clear()
    yield client
    auth._fails.clear()


def test_pages_and_api_require_login(secured):
    r = secured.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert secured.get("/api/batches").status_code == 401
    assert secured.get("/docs", follow_redirects=False).status_code == 303
    assert secured.get("/api/health").status_code == 200  # public


def test_login_logout(secured):
    assert secured.post("/login", data={"password": "nope"}).status_code == 401
    r = secured.post("/login", data={"password": "correct horse battery"}, follow_redirects=False)
    assert r.status_code == 303
    assert "httponly" in r.headers["set-cookie"].lower()
    assert secured.get("/").status_code == 200
    secured.post("/logout")
    secured.cookies.clear()
    assert secured.get("/api/batches").status_code == 401


def test_bearer_token_for_api(secured):
    r = secured.get("/api/batches", headers={"Authorization": "Bearer tok-123"})
    assert r.status_code == 200
    assert secured.get("/api/batches", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_tampered_cookie_rejected(secured):
    exp, _ = auth.make_token().split(".")
    secured.cookies.set(auth.COOKIE, f"{exp}.deadbeef")
    assert secured.get("/api/batches").status_code == 401


def test_lockout_after_failures(secured):
    for _ in range(auth.MAX_FAILS):
        secured.post("/login", data={"password": "bad"})
    r = secured.post("/login", data={"password": "correct horse battery"})
    assert r.status_code == 429
