"""CAS login and user-scoped API key contracts."""

from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.endpoints import auth
from app.core.config import settings

USERNAME = "tester"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_DISABLED", False)
    monkeypatch.setattr(settings, "EIDO_TRUST_GATEWAY", False)
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://testserver/ai-eido/")
    monkeypatch.setattr(settings, "CAS_SERVER_URL", "https://sso.example.test/cas/")
    monkeypatch.setattr(
        settings, "CAS_SERVICE_URL", "http://testserver/ai-eido/api/v1/auth/callback"
    )
    monkeypatch.setattr(settings, "SESSION_SECRET_KEY", "test-api-signing-secret")
    cas = auth._get_cas_client()
    cas.verify_ticket = Mock(
        side_effect=lambda ticket: (USERNAME, {"displayName": "测试用户"}, None)
        if ticket == "valid-ticket"
        else (None, None, None)
    )
    monkeypatch.setattr(auth, "_get_cas_client", lambda **_: cas)
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-cookie-secret")
    app.include_router(auth.router, prefix="/api/v1/auth")
    return TestClient(app, follow_redirects=False)


def login(client):
    return client.get("/api/v1/auth/callback", params={"ticket": "valid-ticket"})


def test_login_redirects_to_cas_and_has_no_password_endpoint(client):
    response = client.get("/api/v1/auth/login")
    assert response.status_code == 307
    redirect = urlparse(response.headers["location"])
    assert redirect.netloc == "sso.example.test"
    assert redirect.path == "/cas/login"
    assert parse_qs(redirect.query)["service"] == [settings.CAS_SERVICE_URL]
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login", data={"username": "admin", "password": "password"}
        ).status_code
        == 405
    )


def test_cas_callback_creates_session_with_display_name(client):
    response = login(client)
    assert response.status_code == 307
    assert response.headers["location"] == settings.FRONTEND_URL + "?login=success"
    assert client.get("/api/v1/auth/me").json() == {"user_id": USERNAME, "username": "测试用户"}


@pytest.mark.parametrize("query,status", [("", 400), ("?ticket=invalid-ticket", 401)])
def test_invalid_callback_never_authenticates(client, query, status):
    assert client.get("/api/v1/auth/callback" + query).status_code == status
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/api-key").status_code == 401


def test_logout_clears_session_and_redirects_to_cas(client):
    login(client)
    response = client.get("/api/v1/auth/logout")
    assert response.status_code == 307
    redirect = urlparse(response.headers["location"])
    assert redirect.netloc == "sso.example.test"
    assert redirect.path == "/cas/logout"
    assert client.get("/api/v1/auth/me").status_code == 401


def test_api_key_is_stable_and_authenticates_without_cookie(client, monkeypatch, tmp_path):
    from app.api.v1.endpoints import sessions
    from app.services.chat.session_store import ChatSessionStore

    path = "/api/v1/auth/api-key"
    assert client.get(path).status_code == 401
    login(client)
    issued = client.get(path)
    assert issued.status_code == 200
    assert issued.headers["cache-control"] == "no-store"
    key = issued.json()["api_key"]

    client.get("/api/v1/auth/logout")
    login(client)
    assert client.get(path).json() == {"api_key": key}
    client.cookies.clear()

    store = ChatSessionStore(tmp_path / "sessions.db")
    store.connect()
    try:
        own_session = store.create_session(USERNAME)
        store.create_session("another-user")
        monkeypatch.setattr(sessions, "get_chat_session_store", lambda: store)
        client.app.include_router(sessions.router, prefix="/api/v1/sessions")
        headers = {"X-API-Key": key}
        assert client.get(path, headers=headers).status_code == 401
        response = client.get("/api/v1/sessions/", headers=headers)
        assert response.status_code == 200
        assert [session["id"] for session in response.json()] == [own_session["id"]]
        assert (
            client.get("/api/v1/sessions/", headers={"X-API-Key": key + "invalid"}).status_code
            == 401
        )
        monkeypatch.setattr(settings, "SESSION_SECRET_KEY", "rotated-test-api-signing-secret")
        assert client.get("/api/v1/sessions/", headers=headers).status_code == 401
    finally:
        store.close()


def test_cas_public_redirect_and_internal_validation_use_their_configured_addresses(monkeypatch):
    monkeypatch.setattr(settings, "CAS_SERVER_URL", "http://localhost:3331/cas/")
    monkeypatch.setattr(settings, "CAS_INTERNAL_URL", "http://cas-server:8080/cas/")
    assert auth._get_cas_client().server_url == "http://localhost:3331/cas/"
    assert auth._get_cas_client(internal=True).server_url == "http://cas-server:8080/cas/"
    monkeypatch.setattr(settings, "CAS_INTERNAL_URL", "")
    assert auth._get_cas_client(internal=True).server_url == settings.CAS_SERVER_URL
