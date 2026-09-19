"""File-backed Claude Code model and provider catalog."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlsplit

import yaml

_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class ProviderSpec:
    """Provider overrides for one model; secret fields are never serialized publicly."""

    base_url: str = ""
    api_key: str = field(default="", repr=False)
    auth_token: str = field(default="", repr=False)
    small_fast_model: str = ""

    def apply(self, base_env: dict[str, str]) -> dict[str, str]:
        env = dict(base_env)
        if self.base_url:
            env["ANTHROPIC_BASE_URL"] = self.base_url.rstrip("/")
        if self.small_fast_model:
            env["ANTHROPIC_SMALL_FAST_MODEL"] = self.small_fast_model
        if self.api_key:
            env["ANTHROPIC_API_KEY"] = self.api_key
            env.pop("ANTHROPIC_AUTH_TOKEN", None)
        elif self.auth_token:
            env["ANTHROPIC_AUTH_TOKEN"] = self.auth_token
            env.pop("ANTHROPIC_API_KEY", None)
        return env

@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    model: str
    description: str = ""
    provider: ProviderSpec = field(default_factory=ProviderSpec, repr=False)

    def public(self) -> dict[str, str]:
        return {
            "id": self.id,
            "label": self.label,
            "model": self.model,
            "description": self.description,
        }

    def sandbox(self) -> dict:
        value: dict = self.public()
        if self.provider.small_fast_model:
            value["provider"] = {"small_fast_model": self.provider.small_fast_model}
        return value

    def agent_env(self, base_env: dict[str, str], *, relay: bool = False) -> dict[str, str]:
        """Build the SDK provider environment without exposing catalog secrets."""
        env = dict(base_env) if relay else self.provider.apply(base_env)
        if relay:
            relay_base = env.get("ANTHROPIC_BASE_URL", "").rstrip("/")
            if not relay_base:
                raise ValueError("沙箱模式缺少 provider relay 地址")
            env["ANTHROPIC_BASE_URL"] = f"{relay_base}/{quote(self.id, safe='')}"
            if self.provider.small_fast_model:
                env["ANTHROPIC_SMALL_FAST_MODEL"] = self.provider.small_fast_model
        env["ANTHROPIC_MODEL"] = self.model
        return env


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
        return {"default": self.default, "models": [item.public() for item in self.models]}

    def sandbox(self) -> dict:
        return {"default": self.default, "models": [item.sandbox() for item in self.models]}


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


def _provider_value(config: dict, name: str, *aliases: str) -> str:
    keys = (name, *aliases)
    direct_values = [config.get(key) for key in keys if str(config.get(key) or "").strip()]
    if len(direct_values) > 1:
        raise ValueError(f"provider.{name} 配置了重复别名")
    direct = direct_values[0] if direct_values else ""
    value = str(direct or "").strip()
    if value.startswith("${") and value.endswith("}"):
        value = _environment_value(value[2:-1].strip())
    env_names = [
        str(config.get(f"{key}_env") or "").strip()
        for key in keys
        if str(config.get(f"{key}_env") or "").strip()
    ]
    if len(env_names) > 1:
        raise ValueError(f"provider.{name}_env 配置了重复别名")
    env_name = env_names[0] if env_names else ""
    if value and env_name:
        raise ValueError(f"provider.{name} 与 provider.{name}_env 不能同时配置")
    return value or (_environment_value(env_name) if env_name else "")


def _environment_value(name: str) -> str:
    value: object = os.getenv(name, "")
    if not value:
        from app.core.config import settings

        value = getattr(settings, name, "")
    get_secret_value = getattr(value, "get_secret_value", None)
    if callable(get_secret_value):
        value = get_secret_value()
    return str(value or "").strip()


def _provider_spec(value: object) -> ProviderSpec:
    if value is None:
        return ProviderSpec()
    if not isinstance(value, dict):
        raise ValueError("provider 必须是对象")
    api_key = _provider_value(value, "api_key", "key")
    auth_token = _provider_value(value, "auth_token")
    if api_key and auth_token:
        raise ValueError("provider.api_key 与 provider.auth_token 只能配置一个")
    base_url = _provider_value(value, "base_url", "baseurl").rstrip("/")
    if base_url:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("provider.base_url 必须是有效的 HTTP(S) 地址")
    return ProviderSpec(
        base_url=base_url,
        api_key=api_key,
        auth_token=auth_token,
        small_fast_model=_provider_value(value, "small_fast_model"),
    )


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
        if not _MODEL_ID_RE.fullmatch(model_id):
            raise ValueError(f"模型 id 格式无效: {model_id}")
        if model_id in seen:
            raise ValueError(f"模型 id 重复: {model_id}")
        seen.add(model_id)
        items.append(
            ModelSpec(
                id=model_id,
                label=str(value.get("label") or "").strip() or model_id,
                model=provider_model,
                description=str(value.get("description") or "").strip(),
                provider=_provider_spec(value.get("provider")),
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
