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


@pytest.mark.skip(reason="需要真实模型凭据；Project API 使用独立的确定性契约测试")
async def test_chat_endpoint():
    """Test chat endpoint (requires valid API key in .env)."""
    # This test requires a valid DeepSeek API key.
