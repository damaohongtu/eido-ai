from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .version import ChromeVersion

_EXTENSION_ID_RE = re.compile(r"^[a-p]{32}$")


class ConfigError(ValueError):
    """Raised when required service configuration is invalid."""


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    extension_id: str
    extension_version: ChromeVersion
    extension_package_path: Path
    public_base_url: str
    extension_min_chrome_version: str | None

    def __post_init__(self) -> None:
        if not _EXTENSION_ID_RE.fullmatch(self.extension_id):
            raise ConfigError("EIDO_EXTENSION_ID must contain exactly 32 letters in the range a-p")
        if not self.extension_package_path.is_absolute():
            raise ConfigError("EIDO_EXTENSION_PACKAGE_PATH must be an absolute path")

        parsed_base_url = urlsplit(self.public_base_url)
        loopback_http = parsed_base_url.scheme == "http" and parsed_base_url.hostname in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
        if not parsed_base_url.hostname or (
            parsed_base_url.scheme != "https" and not loopback_http
        ):
            raise ConfigError(
                "EIDO_EXTENSION_PUBLIC_BASE_URL must use HTTPS, except for loopback development"
            )
        if parsed_base_url.query or parsed_base_url.fragment:
            raise ConfigError("EIDO_EXTENSION_PUBLIC_BASE_URL must not contain a query or fragment")
        if self.extension_min_chrome_version:
            try:
                ChromeVersion.parse(self.extension_min_chrome_version)
            except ValueError as exc:
                raise ConfigError("EIDO_EXTENSION_MIN_CHROME_VERSION is invalid") from exc

    @classmethod
    def from_env(cls) -> Settings:
        raw_version = _required("EIDO_EXTENSION_VERSION")
        try:
            version = ChromeVersion.parse(raw_version)
        except ValueError as exc:
            raise ConfigError("EIDO_EXTENSION_VERSION is invalid") from exc

        min_chrome_version = os.getenv("EIDO_EXTENSION_MIN_CHROME_VERSION", "").strip() or None

        return cls(
            extension_id=_required("EIDO_EXTENSION_ID"),
            extension_version=version,
            extension_package_path=Path(_required("EIDO_EXTENSION_PACKAGE_PATH")),
            public_base_url=_required("EIDO_EXTENSION_PUBLIC_BASE_URL").rstrip("/"),
            extension_min_chrome_version=min_chrome_version,
        )


def validate_release_package(settings: Settings) -> None:
    path = settings.extension_package_path
    if not path.is_file():
        raise ConfigError(f"extension CRX does not exist: {path}")
    if path.stat().st_size < 16:
        raise ConfigError(f"extension CRX is unexpectedly small: {path}")
    with path.open("rb") as package:
        if package.read(4) != b"Cr24":
            raise ConfigError(f"extension package is not a CRX file: {path}")
