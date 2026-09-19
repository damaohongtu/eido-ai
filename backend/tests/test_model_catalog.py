from pathlib import Path

import pytest

from app.core.config import settings
from app.services.model_catalog import load_model_catalog


def _use_catalog(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(settings, "CLAUDE_MODEL_CATALOG_JSON", "")
    monkeypatch.setattr(settings, "CLAUDE_MODELS_FILE", str(path))
    monkeypatch.setattr(settings, "ANTHROPIC_MODEL", "")


def test_loads_file_backed_model_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "models.yaml"
    path.write_text(
        """version: 1
default: glm
models:
  - id: glm
    label: GLM
    model: glm-5.2
  - id: deepseek
    label: DeepSeek
    model: deepseek-chat
""",
        encoding="utf-8",
    )
    _use_catalog(monkeypatch, path)

    catalog = load_model_catalog()

    assert catalog.default == "glm"
    assert catalog.find(None).model == "glm-5.2"
    assert catalog.find("deepseek").model == "deepseek-chat"


def test_legacy_provider_model_can_override_catalog_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "models.yaml"
    path.write_text(
        """version: 1
default: glm
models:
  - {id: glm, model: glm-5.2}
  - {id: deepseek, model: deepseek-chat}
""",
        encoding="utf-8",
    )
    _use_catalog(monkeypatch, path)
    monkeypatch.setattr(settings, "ANTHROPIC_MODEL", "deepseek-chat")

    assert load_model_catalog().default == "deepseek"


def test_rejects_unknown_catalog_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "models.yaml"
    path.write_text(
        "version: 2\ndefault: glm\nmodels:\n  - {id: glm, model: glm-5.2}\n",
        encoding="utf-8",
    )
    _use_catalog(monkeypatch, path)

    with pytest.raises(ValueError, match="不支持的模型配置版本"):
        load_model_catalog()


def test_provider_config_supports_literals_and_environment_without_public_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "models.yaml"
    path.write_text(
        """version: 1
default: glm
models:
  - id: glm
    label: GLM
    model: glm-5.3
    provider:
      base_url: https://glm.example/anthropic/
      api_key_env: TEST_GLM_KEY
      small_fast_model: glm-fast
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_GLM_KEY", "glm-secret")
    _use_catalog(monkeypatch, path)

    catalog = load_model_catalog()
    model = catalog.find("glm")
    env = model.agent_env(
        {
            "ANTHROPIC_BASE_URL": "https://legacy.example",
            "ANTHROPIC_AUTH_TOKEN": "legacy-token",
        }
    )

    assert env == {
        "ANTHROPIC_BASE_URL": "https://glm.example/anthropic",
        "ANTHROPIC_API_KEY": "glm-secret",
        "ANTHROPIC_SMALL_FAST_MODEL": "glm-fast",
        "ANTHROPIC_MODEL": "glm-5.3",
    }
    assert catalog.public()["models"] == [
        {"id": "glm", "label": "GLM", "model": "glm-5.3", "description": ""}
    ]
    assert "glm-secret" not in str(catalog.public())
    assert catalog.sandbox()["models"][0]["provider"] == {
        "small_fast_model": "glm-fast"
    }
    assert "glm-secret" not in str(catalog.sandbox())
    assert "glm.example" not in str(catalog.sandbox())


def test_sandbox_model_env_targets_model_specific_gateway_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "models.yaml"
    path.write_text(
        """default: deepseek
models:
  - {id: deepseek, model: deepseek-chat}
""",
        encoding="utf-8",
    )
    _use_catalog(monkeypatch, path)

    env = load_model_catalog().find("deepseek").agent_env(
        {
            "ANTHROPIC_BASE_URL": "http://eido-gateway:8000/api/v1/provider",
            "ANTHROPIC_AUTH_TOKEN": "tenant-token",
        },
        relay=True,
    )

    assert env["ANTHROPIC_BASE_URL"].endswith("/provider/deepseek")
    assert env["ANTHROPIC_AUTH_TOKEN"] == "tenant-token"
    assert env["ANTHROPIC_MODEL"] == "deepseek-chat"
