"""User-managed MCP server configuration endpoints."""
from __future__ import annotations

import re
import sqlite3
from typing import Literal, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.auth import get_current_user_id
from app.services.mcp_config_store import get_mcp_config_store

router = APIRouter()
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class McpServerPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    transport: Literal["stdio", "http", "sse"]
    enabled: bool = True
    command: Optional[str] = Field(None, max_length=1024)
    args: list[str] = Field(default_factory=list, max_length=64)
    env: dict[str, str] = Field(default_factory=dict)
    url: Optional[str] = Field(None, max_length=4096)
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not _NAME_RE.fullmatch(value):
            raise ValueError("名称仅支持字母、数字、下划线和连字符，且必须以字母或数字开头")
        return value

    @field_validator("args")
    @classmethod
    def validate_args(cls, values: list[str]) -> list[str]:
        if any(len(value) > 4096 or "\x00" in value for value in values):
            raise ValueError("MCP 参数无效或过长")
        return values

    @field_validator("env", "headers")
    @classmethod
    def validate_mapping(cls, values: dict[str, str]) -> dict[str, str]:
        if len(values) > 64:
            raise ValueError("MCP 环境变量或请求头不能超过 64 项")
        for key, value in values.items():
            if not key or len(key) > 256 or len(value) > 8192 or "\x00" in key + value:
                raise ValueError("MCP 环境变量或请求头包含无效内容")
            if "\n" in key or "\r" in key:
                raise ValueError("MCP 配置键不能包含换行")
        return values

    @model_validator(mode="after")
    def validate_transport(self):
        if self.transport == "stdio":
            if not (self.command or "").strip():
                raise ValueError("stdio MCP 必须填写 command")
        else:
            parsed = urlsplit((self.url or "").strip())
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("HTTP/SSE MCP 必须填写有效的 http(s) URL")
        return self

    def sdk_config(self) -> dict:
        if self.transport == "stdio":
            return {
                "type": "stdio",
                "command": (self.command or "").strip(),
                "args": self.args,
                "env": self.env,
            }
        return {
            "type": self.transport,
            "url": (self.url or "").strip(),
            "headers": self.headers,
        }


class McpFileServer(BaseModel):
    type: Literal["stdio", "http", "sse"]
    command: Optional[str] = Field(None, max_length=1024)
    args: list[str] = Field(default_factory=list, max_length=64)
    env: dict[str, str] = Field(default_factory=dict)
    url: Optional[str] = Field(None, max_length=4096)
    headers: dict[str, str] = Field(default_factory=dict)
    disabled: bool = False

    @field_validator("args")
    @classmethod
    def validate_args(cls, values: list[str]) -> list[str]:
        return McpServerPayload.validate_args(values)

    @field_validator("env", "headers")
    @classmethod
    def validate_mapping(cls, values: dict[str, str]) -> dict[str, str]:
        return McpServerPayload.validate_mapping(values)

    @model_validator(mode="after")
    def validate_transport(self):
        if self.type == "stdio":
            if not (self.command or "").strip():
                raise ValueError("stdio MCP 必须填写 command")
        else:
            parsed = urlsplit((self.url or "").strip())
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("HTTP/SSE MCP 必须填写有效的 http(s) URL")
        return self

    def sdk_config(self) -> dict:
        if self.type == "stdio":
            return {
                "type": "stdio",
                "command": (self.command or "").strip(),
                "args": self.args,
                "env": self.env,
            }
        return {
            "type": self.type,
            "url": (self.url or "").strip(),
            "headers": self.headers,
        }


class McpConfigFile(BaseModel):
    mcpServers: dict[str, McpFileServer] = Field(default_factory=dict)

    @field_validator("mcpServers")
    @classmethod
    def validate_servers(
        cls, values: dict[str, McpFileServer]
    ) -> dict[str, McpFileServer]:
        if len(values) > 64:
            raise ValueError("MCP Server 不能超过 64 个")
        for name in values:
            if not _NAME_RE.fullmatch(name):
                raise ValueError(
                    f"MCP 名称 {name!r} 无效：仅支持字母、数字、下划线和连字符"
                )
        return values


def _invalidate_user(user_id: str) -> None:
    from app.services.claude_skill_service import get_claude_skill_service
    from app.services.mcp_status_service import clear_mcp_status_cache

    clear_mcp_status_cache(user_id)
    service = get_claude_skill_service()
    if service is not None:
        service.reset_user(user_id)


def _as_config_file(user_id: str) -> dict:
    servers: dict[str, dict] = {}
    for item in get_mcp_config_store().list_servers(user_id):
        servers[item["name"]] = {
            **item["config"],
            "disabled": not item["enabled"],
        }
    return {"mcpServers": servers}


@router.get("/config")
async def get_config_file(user_id: str = Depends(get_current_user_id)):
    return _as_config_file(user_id)


@router.put("/config")
async def replace_config_file(
    body: McpConfigFile, user_id: str = Depends(get_current_user_id)
):
    normalized = {
        name: {
            "transport": server.type,
            "config": server.sdk_config(),
            "enabled": not server.disabled,
        }
        for name, server in body.mcpServers.items()
    }
    try:
        get_mcp_config_store().replace_servers(user_id, normalized)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _invalidate_user(user_id)
    return _as_config_file(user_id)


@router.get("/servers")
async def list_servers(user_id: str = Depends(get_current_user_id)):
    return get_mcp_config_store().list_servers(user_id)


@router.get("/status")
async def server_statuses(
    refresh: bool = False, user_id: str = Depends(get_current_user_id)
):
    from app.services.mcp_status_service import get_mcp_server_statuses

    return await get_mcp_server_statuses(user_id, refresh=refresh)


@router.post("/servers")
async def create_server(
    body: McpServerPayload, user_id: str = Depends(get_current_user_id)
):
    try:
        result = get_mcp_config_store().create_server(
            user_id,
            name=body.name,
            transport=body.transport,
            config=body.sdk_config(),
            enabled=body.enabled,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="MCP 名称已存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _invalidate_user(user_id)
    return result


@router.put("/servers/{server_id}")
async def update_server(
    server_id: str,
    body: McpServerPayload,
    user_id: str = Depends(get_current_user_id),
):
    try:
        result = get_mcp_config_store().update_server(
            user_id,
            server_id,
            name=body.name,
            transport=body.transport,
            config=body.sdk_config(),
            enabled=body.enabled,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="MCP 名称已存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="MCP 配置不存在")
    _invalidate_user(user_id)
    return result


@router.delete("/servers/{server_id}")
async def delete_server(server_id: str, user_id: str = Depends(get_current_user_id)):
    if not get_mcp_config_store().delete_server(user_id, server_id):
        raise HTTPException(status_code=404, detail="MCP 配置不存在")
    _invalidate_user(user_id)
    return {"deleted": True}
