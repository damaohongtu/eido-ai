"""File-backed Claude Code model catalog."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    model: str
    description: str = ""


@dataclass(frozen=True)
class ModelCatalog:
    default: str
    models: tuple[ModelSpec, ...]

    def find(self, model_id: str | None) -> ModelSpec:
        selected = (model_id or self.default).strip()
        for item in self.models:
            if item.id == selected:
                return item
        raise ValueError("模型未配置，请从模型列表选择")

    def public(self) -> dict:
        return {"default": self.default, "models": [asdict(item) for item in self.models]}


def _catalog_path() -> Path:
    from app.core.config import settings

    if settings.CLAUDE_MODELS_FILE.strip():
        return Path(settings.CLAUDE_MODELS_FILE).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "config" / "models.yaml"


def _raw_catalog() -> dict:
    from app.core.config import settings

    try:
        if settings.CLAUDE_MODEL_CATALOG_JSON.strip():
            value = json.loads(settings.CLAUDE_MODEL_CATALOG_JSON)
        else:
            path = _catalog_path()
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"模型配置格式错误: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("模型配置必须是对象")
    return value


def load_model_catalog() -> ModelCatalog:
    raw = _raw_catalog()
    version = raw.get("version", 1)
    if version != 1:
        raise ValueError(f"不支持的模型配置版本: {version}")
    items: list[ModelSpec] = []
    seen: set[str] = set()
    for value in raw.get("models") or []:
        if not isinstance(value, dict):
            raise ValueError("models 中的每一项必须是对象")
        model_id = str(value.get("id") or "").strip()
        provider_model = str(value.get("model") or "").strip()
        if not model_id or not provider_model:
            raise ValueError("每个模型都必须配置 id 和 model")
        if model_id in seen:
            raise ValueError(f"模型 id 重复: {model_id}")
        seen.add(model_id)
        items.append(
            ModelSpec(
                id=model_id,
                label=str(value.get("label") or "").strip() or model_id,
                model=provider_model,
                description=str(value.get("description") or "").strip(),
            )
        )
    if not items:
        raise ValueError("模型配置至少需要一个模型")

    configured_default = str(raw.get("default") or "").strip()
    default = configured_default or items[0].id
    from app.core.config import settings

    legacy_default = settings.ANTHROPIC_MODEL.strip()
    if legacy_default:
        match = next((item for item in items if item.model == legacy_default), None)
        if match:
            default = match.id
    if default not in seen:
        raise ValueError(f"默认模型未定义: {default}")
    return ModelCatalog(default=default, models=tuple(items))
