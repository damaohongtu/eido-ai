"""AUTH_MODE=local 登录流契约测试。

覆盖：登录成功/失败重定向、next 回跳参数、开放重定向防护、登出回跳。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.endpoints import auth as auth_module
from app.core.config import settings
from app.core.local_auth import hash_password

USERNAME = "tester"
PASSWORD = "s3cret-pass"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "local")
    monkeypatch.setattr(settings, "AUTH_DISABLED", False)
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://testserver/ai-eido/")
    monkeypatch.setattr(settings, "LOCAL_AUTH_USERNAME", USERNAME)
    monkeypatch.setattr(
        settings,
        "LOCAL_AUTH_PASSWORD_HASH",
        SecretStr(hash_password(PASSWORD, iterations=1000)),
    )
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(auth_module.router, prefix="/api/v1/auth")
    # 模块级限速器在用例间复位，避免同一测试 IP 被上一条用例锁死
    auth_module._login_throttle.reset("testclient")
    return TestClient(app, follow_redirects=False)


def _login(client: TestClient, **overrides) -> object:
    data = {"username": USERNAME, "password": PASSWORD}
    data.update(overrides)
    return client.post("/api/v1/auth/login", data=data)


def test_login_page_renders(client):
    resp = client.get("/api/v1/auth/login")
    assert resp.status_code == 200
    assert "请输入账号密码登录" in resp.text
    assert '<form method="post">' in resp.text


def test_login_success_default_redirect(client):
    resp = _login(client)
    assert resp.status_code == 303
    assert resp.headers["location"] == "http://testserver/ai-eido/?login=success"
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user_id"] == USERNAME


def test_login_success_honors_next(client):
    resp = client.post(
        "/api/v1/auth/login?next=%2Fai-eido%2Fm%2F",
        data={"username": USERNAME, "password": PASSWORD},
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/ai-eido/m/"
    assert client.get("/api/v1/auth/me").json()["user_id"] == USERNAME


@pytest.mark.parametrize(
    "malicious",
    [
        "//evil.com",
        "http://evil.com",
        "/\\evil.com",
        "/other-app/",
        "",
    ],
)
def test_login_rejects_unsafe_next(client, malicious):
    from urllib.parse import quote

    resp = client.post(
        f"/api/v1/auth/login?next={quote(malicious, safe='')}",
        data={"username": USERNAME, "password": PASSWORD},
    )
    assert resp.status_code == 303
    # 危险 next 一律回落到默认跳转，绝不外跳
    assert resp.headers["location"] == "http://testserver/ai-eido/?login=success"


def test_login_failure_keeps_next(client):
    resp = client.post(
        "/api/v1/auth/login?next=%2Fai-eido%2Fm%2F",
        data={"username": USERNAME, "password": "wrong"},
    )
    assert resp.status_code == 303
    assert (
        resp.headers["location"]
        == "http://testserver/ai-eido/api/v1/auth/login?error=1&next=%2Fai-eido%2Fm%2F"
    )
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_throttle_locks_out(client):
    for _ in range(10):
        resp = _login(client, password="wrong")
        assert resp.status_code == 303
        assert "error=1" in resp.headers["location"]
    locked = _login(client)
    assert locked.status_code == 303
    assert "locked=1" in locked.headers["location"]


def test_logout_honors_next(client):
    _login(client)
    resp = client.get("/api/v1/auth/logout?next=%2Fai-eido%2Fm%2F")
    assert resp.status_code == 307
    assert resp.headers["location"] == "/ai-eido/m/"
    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_default_redirect(client):
    _login(client)
    resp = client.get("/api/v1/auth/logout")
    assert resp.status_code == 307
    assert resp.headers["location"] == "http://testserver/ai-eido/"
