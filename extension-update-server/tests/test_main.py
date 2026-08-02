import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi.testclient import TestClient

from extension_updater.config import Settings
from extension_updater.main import create_app
from extension_updater.protocol import UPDATE_NAMESPACE
from extension_updater.version import ChromeVersion

EXTENSION_ID = "abcdefghijklmnopabcdefghijklmnop"


def make_settings(tmp_path: Path) -> Settings:
    package_path = tmp_path / "eido-extension.crx"
    package_path.write_bytes(b"Cr24" + b"test-package-data")
    return Settings(
        extension_id=EXTENSION_ID,
        extension_version=ChromeVersion.parse("0.1.3"),
        extension_package_path=package_path,
        public_base_url="https://updates.example.com",
        extension_min_chrome_version="116",
    )


def updatecheck(response):
    root = ET.fromstring(response.content)
    app = root.find(f"{{{UPDATE_NAMESPACE}}}app")
    assert app is not None
    node = app.find(f"{{{UPDATE_NAMESPACE}}}updatecheck")
    assert node is not None
    return node


def test_offers_newer_release_with_server_download_url(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        response = client.get(
            "/updates.xml",
            params={"x": f"id={EXTENSION_ID}&v=0.1.2&uc="},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("application/xml")
    assert updatecheck(response).attrib == {
        "codebase": "https://updates.example.com/releases/0.1.3/eido-extension.crx",
        "version": "0.1.3",
        "prodversionmin": "116",
    }


def test_returns_no_update_for_current_or_unknown_extension(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        current = client.get(
            "/updates.xml", params={"x": f"id={EXTENSION_ID}&v=0.1.3"}
        )
        unknown = client.get(
            "/updates.xml",
            params={"x": "id=ponmlkjihgfedcbaponmlkjihgfedcba&v=0.1.0"},
        )

    assert updatecheck(current).attrib == {"status": "noupdate"}
    assert updatecheck(unknown).attrib == {"status": "noupdate"}


def test_returns_400_for_invalid_update_request(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        response = client.get("/updates.xml", params={"x": f"id={EXTENSION_ID}"})
    assert response.status_code == 400


def test_serves_only_the_configured_versioned_crx(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        current = client.get("/releases/0.1.3/eido-extension.crx")
        metadata = client.head("/releases/0.1.3/eido-extension.crx")
        missing = client.get("/releases/0.1.2/eido-extension.crx")

    assert current.status_code == 200
    assert current.content.startswith(b"Cr24")
    assert current.headers["content-type"] == "application/x-chrome-extension"
    assert current.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert metadata.status_code == 200
    assert metadata.content == b""
    assert metadata.headers["content-length"] == str(len(current.content))
    assert missing.status_code == 404
