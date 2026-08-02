from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import parse_qs

from .version import ChromeVersion

UPDATE_NAMESPACE = "http://www.google.com/update2/response"
ET.register_namespace("", UPDATE_NAMESPACE)


@dataclass(frozen=True)
class UpdateRequest:
    extension_id: str
    current_version: ChromeVersion


@dataclass(frozen=True)
class UpdateResponse:
    extension_id: str
    version: str | None = None
    codebase: str | None = None
    min_chrome_version: str | None = None

    @property
    def has_update(self) -> bool:
        return bool(self.version and self.codebase)


def parse_update_requests(raw_values: list[str]) -> list[UpdateRequest]:
    if not raw_values:
        raise ValueError("missing x update parameter")
    if len(raw_values) > 20:
        raise ValueError("too many x update parameters")

    requests: list[UpdateRequest] = []
    for raw_value in raw_values:
        if len(raw_value) > 2048:
            raise ValueError("x update parameter is too long")
        values = parse_qs(raw_value, keep_blank_values=True, strict_parsing=False)
        extension_ids = values.get("id", [])
        versions = values.get("v", [])
        if len(extension_ids) != 1 or len(versions) != 1:
            raise ValueError("x update parameter must contain exactly one id and v")
        current_version = ChromeVersion.parse(versions[0], allow_zero=True)
        requests.append(
            UpdateRequest(extension_id=extension_ids[0], current_version=current_version)
        )
    return requests


def render_update_manifest(responses: list[UpdateResponse]) -> bytes:
    root = ET.Element(f"{{{UPDATE_NAMESPACE}}}gupdate", {"protocol": "2.0"})
    for response in responses:
        app = ET.SubElement(root, f"{{{UPDATE_NAMESPACE}}}app", {"appid": response.extension_id})
        if response.has_update:
            attributes = {
                "codebase": response.codebase or "",
                "version": response.version or "",
            }
            if response.min_chrome_version:
                attributes["prodversionmin"] = response.min_chrome_version
            ET.SubElement(app, f"{{{UPDATE_NAMESPACE}}}updatecheck", attributes)
        else:
            ET.SubElement(
                app,
                f"{{{UPDATE_NAMESPACE}}}updatecheck",
                {"status": "noupdate"},
            )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)

