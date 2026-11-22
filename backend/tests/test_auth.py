"""CAS, GitHub and OIDC login contracts using real OAuth state and ID token checks."""

import base64
import hashlib
import json
import time
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from authlib.jose import JsonWebKey, jwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.endpoints import auth
from app.core.config import settings

USERNAME = "tester"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_DISABLED", False)
    monkeypatch.setattr(settings, "AUTH_ALLOWED_USER_IDS", "")
    monkeypatch.setattr(settings, "AUTH_ALLOWED_GITHUB_USERS", "")
    monkeypatch.setattr(settings, "EIDO_TRUST_GATEWAY", False)
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://testserver/ai-eido/")
    monkeypatch.setattr(settings, "CAS_SERVER_URL", "https://sso.example.test/cas/")
    monkeypatch.setattr(
        settings, "CAS_SERVICE_URL", "http://testserver/ai-eido/api/v1/auth/callback"
    )
    monkeypatch.setattr(settings, "SESSION_SECRET_KEY", "test-api-signing-secret")
    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "")
    monkeypatch.setattr(settings, "OIDC_PROVIDERS_JSON", SecretStr("[]"))
    cas = auth.get_cas_client()
    cas.verify_ticket = Mock(
        side_effect=lambda ticket: (USERNAME, {"displayName": "测试用户"}, None)
        if ticket == "valid-ticket"
        else (None, None, None)
    )
    monkeypatch.setattr(auth, "get_cas_client", lambda **_: cas)
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


def test_unconfigured_cas_does_not_break_github_login(client, github, monkeypatch):
    login(client)
    monkeypatch.setattr(settings, "CAS_SERVER_URL", "")
    assert client.get("/api/v1/auth/providers").json() == [{"id": "github", "name": "GitHub"}]
    assert client.get("/api/v1/auth/login").status_code == 503
    assert client.get("/api/v1/auth/login/github").status_code == 302
    assert client.get("/api/v1/auth/logout").headers["location"] == settings.FRONTEND_URL
    assert client.get("/api/v1/auth/me").status_code == 401


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
    assert auth.get_cas_client().server_url == "http://localhost:3331/cas/"
    assert auth.get_cas_client(internal=True).server_url == "http://cas-server:8080/cas/"
    monkeypatch.setattr(settings, "CAS_INTERNAL_URL", "")
    assert auth.get_cas_client(internal=True).server_url == settings.CAS_SERVER_URL


@pytest.fixture
def oauth_http(monkeypatch):
    """Mock only the upstream HTTP transport; Authlib's protocol checks stay real."""
    original = auth.get_login_providers

    def install(handler):
        transport = httpx.MockTransport(handler)

        def providers():
            items = original()
            for provider in items.values():
                provider.client.client_kwargs["transport"] = transport
            return items

        monkeypatch.setattr(auth, "get_login_providers", providers)

    return install


def _begin_oauth(client, provider):
    response = client.get(f"/api/v1/auth/login/{provider}")
    assert response.status_code == 302, response.text
    params = parse_qs(urlparse(response.headers["location"]).query)
    assert params["code_challenge_method"] == ["S256"]
    return {key: values[0] for key, values in params.items()}


def _finish_oauth(client, provider, state):
    return client.get(
        f"/api/v1/auth/callback/{provider}", params={"code": "test-code", "state": state}
    )


@pytest.fixture
def github(client, monkeypatch, oauth_http):
    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "github-test-client")
    monkeypatch.setattr(settings, "GITHUB_CLIENT_SECRET", SecretStr("github-test-secret"))
    monkeypatch.setattr(settings, "GITHUB_REDIRECT_URI", "")
    state = {"profile": {"id": 42, "login": USERNAME, "name": "GitHub User"}, "requests": []}

    async def upstream(request):
        state["requests"].append(request)
        if request.url.path == "/login/oauth/access_token":
            body = parse_qs((await request.aread()).decode())
            assert body["client_id"] == ["github-test-client"]
            assert body["client_secret"] == ["github-test-secret"]
            verifier = body["code_verifier"][0]
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .decode()
                .rstrip("=")
            )
            assert challenge == state["authorization"]["code_challenge"]
            assert body["redirect_uri"] == [state["authorization"]["redirect_uri"]]
            return httpx.Response(
                200, json={"access_token": "test-access-token", "token_type": "bearer"}
            )
        assert str(request.url) == "https://api.github.com/user"
        assert request.headers["authorization"] == "Bearer test-access-token"
        return httpx.Response(200, json=state["profile"])

    oauth_http(upstream)
    return state


def test_configured_providers_are_public_and_cas_is_always_available(client, github):
    response = client.get("/api/v1/auth/providers")
    assert response.json() == [{"id": "cas", "name": "CAS"}, {"id": "github", "name": "GitHub"}]
    assert "secret" not in response.text
    assert client.get("/api/v1/auth/login/missing").status_code == 404
    assert client.get("/api/v1/auth/login").headers["location"].startswith(settings.CAS_SERVER_URL)


def test_single_tenant_allowlist_covers_login_and_api_keys(client, github, monkeypatch):
    from app.core.api_key import issue_api_key
    from app.core.auth import get_current_user_id

    monkeypatch.setattr(settings, "AUTH_ALLOWED_USER_IDS", "oauth_github_42")

    @client.app.get("/protected")
    def protected(user_id: str = Depends(get_current_user_id)):
        return {"user_id": user_id}

    github["profile"]["id"] = 43
    github["authorization"] = _begin_oauth(client, "github")
    assert _finish_oauth(client, "github", github["authorization"]["state"]).status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.get(
            "/protected", headers={"X-API-Key": issue_api_key("oauth_github_43")}
        ).status_code
        == 403
    )

    github["profile"]["id"] = 42
    github["authorization"] = _begin_oauth(client, "github")
    assert _finish_oauth(client, "github", github["authorization"]["state"]).status_code == 307
    key = client.get("/api/v1/auth/api-key").json()["api_key"]
    assert client.get("/protected", headers={"X-API-Key": key}).json() == {
        "user_id": "oauth_github_42"
    }
    monkeypatch.setattr(settings, "AUTH_ALLOWED_USER_IDS", "oauth_github_99")
    assert client.get("/api/v1/auth/me").status_code == 403
    assert client.get("/api/v1/auth/api-key").status_code == 403


def test_github_account_allowlist_rejects_other_logins(client, github, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ALLOWED_GITHUB_USERS", "damaohongtu")
    github["authorization"] = _begin_oauth(client, "github")
    response = _finish_oauth(client, "github", github["authorization"]["state"])
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "当前 GitHub 账号无权访问"
    assert client.get("/api/v1/auth/me").status_code == 401


def test_github_account_allowlist_matches_login_case_insensitively(client, github, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ALLOWED_GITHUB_USERS", " someone-else , TESTER ")
    github["authorization"] = _begin_oauth(client, "github")
    assert _finish_oauth(client, "github", github["authorization"]["state"]).status_code == 307
    assert client.get("/api/v1/auth/me").json()["user_id"] == "oauth_github_42"


def test_github_login_uses_stable_id_and_separate_api_key_from_cas(client, github):
    from app.core.api_key import verify_api_key

    login(client)
    cas_key = client.get("/api/v1/auth/api-key").json()["api_key"]
    client.get("/api/v1/auth/logout")
    github["authorization"] = _begin_oauth(client, "github")
    assert (
        github["authorization"]["redirect_uri"]
        == "http://testserver/ai-eido/api/v1/auth/callback/github"
    )
    assert github["authorization"]["scope"] == "read:user"
    response = _finish_oauth(client, "github", github["authorization"]["state"])
    assert response.status_code == 307, response.text
    assert client.get("/api/v1/auth/me").json() == {
        "user_id": "oauth_github_42",
        "username": "GitHub User",
    }
    key = client.get("/api/v1/auth/api-key").json()["api_key"]
    assert key != cas_key and verify_api_key(key) == "oauth_github_42"
    assert client.get("/api/v1/auth/logout").headers["location"] == settings.FRONTEND_URL
    assert client.get("/api/v1/auth/me").status_code == 401

    github["profile"].update(login="renamed-user", name="Renamed User")
    github["authorization"] = _begin_oauth(client, "github")
    assert _finish_oauth(client, "github", github["authorization"]["state"]).status_code == 307
    assert client.get("/api/v1/auth/api-key").json()["api_key"] == key
    assert _finish_oauth(client, "github", github["authorization"]["state"]).status_code == 401


@pytest.mark.parametrize("case", ["wrong_state", "missing_cookie", "denied"])
def test_github_callback_rejects_untrusted_flow_before_token_exchange(client, github, case):
    authorization = _begin_oauth(client, "github")
    if case == "missing_cookie":
        client.cookies.clear()
    if case == "denied":
        response = client.get(
            "/api/v1/auth/callback/github",
            params={"error": "access_denied", "state": authorization["state"]},
        )
    else:
        response = _finish_oauth(
            client, "github", "wrong" if case == "wrong_state" else authorization["state"]
        )
    assert response.status_code == 401
    assert github["requests"] == []
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.fixture
def oidc(client, monkeypatch, oauth_http, request):
    issuer = "https://identity.example.test"
    auth_method = getattr(request, "param", "client_secret_basic")
    monkeypatch.setattr(
        settings,
        "OIDC_PROVIDERS_JSON",
        SecretStr(
            json.dumps(
                [
                    {
                        "id": "work",
                        "name": "企业登录",
                        "issuer": issuer,
                        "client_id": "oidc-test-client",
                        "client_secret": "oidc-test-secret",
                        "token_endpoint_auth_method": auth_method,
                    }
                ]
            )
        ),
    )
    key = JsonWebKey.generate_key("RSA", 2048, {"kid": "test-key"}, is_private=True)
    state = {"claims": {}, "key": key}

    def upstream(request):
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": issuer,
                    "authorization_endpoint": issuer + "/authorize",
                    "token_endpoint": issuer + "/token",
                    "jwks_uri": issuer + "/jwks",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [key.as_dict(is_private=False)]})
        assert request.url.path == "/token"
        body = parse_qs(request.content.decode())
        if auth_method == "client_secret_post":
            assert body["client_id"] == ["oidc-test-client"]
            assert body["client_secret"] == ["oidc-test-secret"]
        else:
            assert request.headers["authorization"].startswith("Basic ")
        claims = {
            "iss": issuer,
            "sub": "immutable-subject",
            "aud": "oidc-test-client",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "nonce": state["authorization"]["nonce"],
            "name": "企业用户",
            **state["claims"],
        }
        encoded = jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, state["key"]).decode()
        return httpx.Response(
            200,
            json={"access_token": "oidc-test-token", "token_type": "bearer", "id_token": encoded},
        )

    oauth_http(upstream)
    return state


@pytest.mark.parametrize("oidc", ["client_secret_basic", "client_secret_post"], indirect=True)
def test_generic_oidc_login_and_api_key_without_provider_specific_routes(client, oidc):
    oidc["authorization"] = _begin_oauth(client, "work")
    assert oidc["authorization"]["redirect_uri"].endswith("/api/v1/auth/callback/work")
    response = _finish_oauth(client, "work", oidc["authorization"]["state"])
    assert response.status_code == 307, response.text
    user = client.get("/api/v1/auth/me").json()
    assert user["user_id"].startswith("oauth_work_")
    assert user["username"] == "企业用户"
    assert client.get("/api/v1/auth/api-key").status_code == 200
    assert client.get("/api/v1/auth/logout").headers["location"] == settings.FRONTEND_URL
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize(
    "claim,value",
    [
        ("iss", "https://untrusted.example.test"),
        ("aud", "wrong-client"),
        ("nonce", "wrong-nonce"),
        ("exp", 1),
    ],
)
def test_oidc_rejects_invalid_id_token_claims(client, oidc, claim, value):
    oidc["claims"][claim] = value
    oidc["authorization"] = _begin_oauth(client, "work")
    response = _finish_oauth(client, "work", oidc["authorization"]["state"])
    assert response.status_code == 401, response.text
    assert client.get("/api/v1/auth/me").status_code == 401


def test_oidc_rejects_id_token_signed_by_another_key(client, oidc):
    oidc["key"] = JsonWebKey.generate_key("RSA", 2048, {"kid": "test-key"}, is_private=True)
    oidc["authorization"] = _begin_oauth(client, "work")
    response = _finish_oauth(client, "work", oidc["authorization"]["state"])
    assert response.status_code == 401, response.text
    assert client.get("/api/v1/auth/me").status_code == 401
