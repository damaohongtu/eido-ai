"""
Tests for chat endpoints.
"""
import pytest
from fastapi.testclient import TestClient as FastAPITestClient
from app.main import app

client = FastAPITestClient(app)


def test_health_check():
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_root():
    """Test root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()


def test_request_trace_id_is_reused_and_returned(caplog):
    trace_id = "client-trace-123"
    with caplog.at_level("INFO", logger="app.main"):
        response = client.get("/", headers={"X-Trace-Id": trace_id})

    assert response.headers["X-Trace-Id"] == trace_id
    request_records = [
        record
        for record in caplog.records
        if record.name == "app.main" and record.getMessage().startswith(("→", "←"))
    ]
    assert request_records
    assert all(record.trace_id == trace_id for record in request_records)


def test_request_trace_id_is_generated_for_invalid_input():
    response = client.get("/", headers={"X-Trace-Id": "invalid trace id\n"})

    trace_id = response.headers["X-Trace-Id"]
    assert len(trace_id) == 32
    assert trace_id.isalnum()


@pytest.mark.skip(reason="需要真实模型凭据；Project API 使用独立的确定性契约测试")
async def test_chat_endpoint():
    """Test chat endpoint (requires valid API key in .env)."""
    # This test requires a valid DeepSeek API key.
