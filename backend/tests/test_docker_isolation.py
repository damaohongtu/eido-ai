"""Opt-in real Docker test, with synthetic credentials and an offline provider.

EIDO_TEST_USER_IMAGE=eido-user:codex-isolation-test python -m pytest tests/test_docker_isolation.py -v
Only resources named with this test's random ID are created/removed.
"""

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("EIDO_TEST_USER_IMAGE"), reason="requires opt-in Docker image"
)


def token(user):
    key = hmac.new(
        b"test-session-master-secret", f"eido-v1:user-token:{user}".encode(), hashlib.sha256
    ).hexdigest()
    payload = f"{user}:{int(time.time()) + 1800}"
    signature = hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode()


def test_real_tenant_isolation_and_native_resume():
    import docker

    client = docker.from_env()
    run_id = "eido-check-" + uuid.uuid4().hex[:8]
    users = [run_id + "-alice", run_id + "-bob"]
    network = client.networks.create(run_id, driver="bridge")
    gateway = None
    nginx = None
    root = Path(__file__).resolve().parent
    try:
        gateway = client.containers.run(
            os.environ["EIDO_TEST_USER_IMAGE"],
            name=run_id,
            detach=True,
            user="0:0",
            network=network.name,
            ports={"80/tcp": ("127.0.0.1", None)},
            environment={
                "EIDO_TRUST_GATEWAY": "0",
                "EIDO_SANDBOX_MODE": "docker",
                "EIDO_NET": run_id,
                "EIDO_GATEWAY_CONTAINER": run_id,
                "EIDO_GATEWAY_INTERNAL_URL": "http://eido-gateway/ai-eido",
                "EIDO_GATEWAY_SECRET": "test-gateway-master-secret",
                "SESSION_SECRET_KEY": "test-session-master-secret",
                "EIDO_USER_TOKEN_SECRET": "",
                "EIDO_USER_IMAGE": os.environ["EIDO_TEST_USER_IMAGE"],
                "EIDO_SANDBOX_HEALTH_TTL": "0",
                "EIDO_DATA_ROOT": "/data",
                "AUTH_DISABLED": "False",
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:9000",
                "ANTHROPIC_API_KEY": "test-master-provider-key",
                "ANTHROPIC_AUTH_TOKEN": "",
                "ANTHROPIC_MODEL": "test-model",
                "CLAUDE_MODEL_CATALOG_JSON": (
                    '{"default":"test","models":['
                    '{"id":"test","label":"Test","model":"test-model"}]}'
                ),
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            },
            volumes={
                "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                str(root / "fixtures" / "fake_anthropic.py"): {
                    "bind": "/test/fake.py",
                    "mode": "ro",
                },
            },
            command=[
                "python",
                "-c",
                'import subprocess,os; subprocess.Popen(["python","/test/fake.py"]); os.execvp("uvicorn",["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"])',
            ],
        )
        nginx = client.containers.run(
            os.getenv("EIDO_TEST_NGINX_IMAGE", "nginx:alpine"),
            name=run_id + "-nginx",
            detach=True,
            network_mode=f"container:{gateway.id}",
            volumes={
                str(root.parent.parent / "docker/nginx.conf"): {
                    "bind": "/etc/nginx/conf.d/default.conf",
                    "mode": "ro",
                }
            },
            command=["sh", "-c", "mkdir -p /var/log/eido/nginx && exec nginx -g 'daemon off;'"],
        )
        gateway.reload()
        port = gateway.attrs["NetworkSettings"]["Ports"]["80/tcp"][0]["HostPort"]
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}/ai-eido", timeout=120, trust_env=False
        ) as api:
            for _ in range(120):
                try:
                    if api.get("/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                pytest.fail(gateway.logs(tail=50).decode())
            identities = [{"X-Eido-User-Token": token(user)} for user in users]
            sessions = []
            for headers in identities:
                response = api.post(
                    "/api/v1/sessions/", headers=headers, json={"title": "Isolation test"}
                )
                assert response.status_code == 200, response.text + gateway.logs(tail=15).decode()
                sessions.append(response.json()["id"])
            # Gateway routes never let Bob access Alice's session.
            assert (
                api.get(f"/api/v1/sessions/{sessions[0]}", headers=identities[1]).status_code == 404
            )
            alice, bob = [client.containers.get("eido-user-" + user) for user in users]
            alice_env = dict(pair.split("=", 1) for pair in alice.attrs["Config"]["Env"])
            bob_env = dict(pair.split("=", 1) for pair in bob.attrs["Config"]["Env"])
            assert "test-master-provider-key" not in alice_env.values()
            assert alice_env["EIDO_GATEWAY_SECRET"] != bob_env["EIDO_GATEWAY_SECRET"]
            for container in (alice, bob):
                host = container.attrs["HostConfig"]
                assert host["ReadonlyRootfs"] and host["CapDrop"] == ["ALL"]
                assert not host["PortBindings"]
                assert container.exec_run(["test", "!", "-f", "/app/.env"]).exit_code == 0
                assert b"2.1.276" in container.exec_run(["claude", "--version"]).output
                assert all(
                    m["Destination"] != "/var/run/docker.sock" for m in container.attrs["Mounts"]
                )
                assert container.exec_run(["sh", "-c", "echo denied > /app/escape"]).exit_code != 0
            assert not (
                alice.attrs["NetworkSettings"]["Networks"].keys()
                & bob.attrs["NetworkSettings"]["Networks"].keys()
            )
            bob_ip = next(iter(bob.attrs["NetworkSettings"]["Networks"].values()))["IPAddress"]
            probe = alice.exec_run(
                [
                    "python",
                    "-c",
                    f'import socket; s=socket.create_connection(("{bob_ip}",8000),timeout=2)',
                ]
            )
            assert probe.exit_code != 0, "tenant bridge must not reach another tenant"
            # Even a gateway-level request with Alice's exposed trust credential cannot impersonate Bob.
            forged = api.get(
                "/api/v1/sessions/",
                headers={
                    "X-Eido-User-Id": users[1],
                    "X-Eido-Gateway-Secret": alice_env["EIDO_GATEWAY_SECRET"],
                },
            )
            assert forged.status_code == 401

            def turn(text):
                response = api.post(
                    "/api/v1/chat/chat",
                    headers=identities[0],
                    json={
                        "session_id": sessions[0],
                        "assistant_message_id": uuid.uuid4().hex,
                        "messages": [{"id": uuid.uuid4().hex, "role": "user", "content": text}],
                    },
                )
                assert response.status_code == 200, response.text
                events = [
                    json.loads(line[6:])
                    for line in response.text.splitlines()
                    if line.startswith("data: ") and line != "data: [DONE]"
                ]
                assert not [e for e in events if e.get("type") == "error"], response.text
                return "".join(e.get("content", "") for e in events if e.get("type") == "content")

            assert "EIDO_MARKER_ALPHA742" in turn("Remember EIDO_MARKER_ALPHA742.")
            assert "EIDO_MARKER_ALPHA742" in turn("Return the marker from our prior conversation.")
            before = api.get(f"/api/v1/sessions/{sessions[0]}", headers=identities[0]).json()
            assert before["claude_session_id"]
            alice.stop(timeout=15)
            alice.remove()
            assert "EIDO_MARKER_ALPHA742" in turn("After restart, return the earlier marker.")
            restored = client.containers.get("eido-user-" + users[0])
            assert restored.id != alice.id
            after = api.get(f"/api/v1/sessions/{sessions[0]}", headers=identities[0]).json()
            assert before["claude_session_id"] == after["claude_session_id"]
            assert b"mode=resume" in restored.logs()
            # The scheduler runs on gateway, but a script must run in the tenant.
            created = api.post(
                "/api/v1/tasks/",
                headers=identities[0],
                json={
                    "name": "Script isolation",
                    "schedule": "interval:3600",
                    "type": "script",
                    "params": {
                        "script_path": "/bin/sh",
                        "args": [
                            "-c",
                            "id -u; test ! -e /var/run/docker.sock && echo SCRIPT_ISOLATED",
                        ],
                    },
                },
            )
            assert created.status_code == 200, created.text
            started = api.post(f"/api/v1/tasks/{created.json()['id']}/run", headers=identities[0])
            assert started.status_code == 200, started.text
            for _ in range(60):
                detail = api.get(
                    f"/api/v1/sessions/{started.json()['session_id']}", headers=identities[0]
                ).json()
                answer = next(
                    (
                        m["content"]
                        for m in detail["messages"]
                        if m["role"] == "assistant" and m["content"]
                    ),
                    "",
                )
                if answer:
                    assert "10001" in answer and "SCRIPT_ISOLATED" in answer, answer
                    break
                time.sleep(0.2)
            else:
                pytest.fail("script did not complete")
            print(
                "Verified: separate network/credentials/volumes, read-only non-root runtime, streaming, native resume after container recreation"
            )
    finally:
        if gateway:
            # Keep diagnostics local and free of real provider credentials.
            Path("/tmp/eido-docker-test-gateway.log").write_bytes(gateway.logs(tail=200))
        for user in users:
            name = "eido-user-" + user
            try:
                container = client.containers.get(name)
                Path(f"/tmp/{user}.log").write_bytes(container.logs(tail=150))
                container.remove(force=True, v=True)
            except docker.errors.NotFound:
                pass
            try:
                client.volumes.get(name).remove()
            except docker.errors.NotFound:
                pass
        if nginx:
            nginx.remove(force=True, v=True)
        if gateway:
            gateway.remove(force=True, v=True)
        for user in users:
            try:
                client.networks.get(f"{run_id}-user-{user}").remove()
            except docker.errors.NotFound:
                pass
        network.remove()
        client.close()
