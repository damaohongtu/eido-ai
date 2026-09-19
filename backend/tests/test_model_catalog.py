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
