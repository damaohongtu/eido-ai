import xml.etree.ElementTree as ET

import pytest

from extension_updater.protocol import (
    UPDATE_NAMESPACE,
    UpdateResponse,
    parse_update_requests,
    render_update_manifest,
)


def test_parses_chrome_nested_update_parameters() -> None:
    result = parse_update_requests(
        ["id=abcdefghijklmnopabcdefghijklmnop&v=0.1.2&uc="]
    )
    assert result[0].extension_id == "abcdefghijklmnopabcdefghijklmnop"
    assert result[0].current_version.value == "0.1.2"


def test_rejects_missing_version() -> None:
    with pytest.raises(ValueError, match="exactly one id and v"):
        parse_update_requests(["id=abcdefghijklmnopabcdefghijklmnop"])


def test_manifest_escapes_signed_url_and_renders_no_update() -> None:
    signed_url = "https://bucket.example/release.crx?q-sign=abc&q-key-time=1&token=x"
    xml_bytes = render_update_manifest(
        [
            UpdateResponse(
                extension_id="abcdefghijklmnopabcdefghijklmnop",
                version="0.1.3",
                codebase=signed_url,
                min_chrome_version="116",
            ),
            UpdateResponse(extension_id="ponmlkjihgfedcbaponmlkjihgfedcba"),
        ]
    )

    assert b"&amp;" in xml_bytes
    root = ET.fromstring(xml_bytes)
    apps = root.findall(f"{{{UPDATE_NAMESPACE}}}app")
    offered = apps[0].find(f"{{{UPDATE_NAMESPACE}}}updatecheck")
    no_update = apps[1].find(f"{{{UPDATE_NAMESPACE}}}updatecheck")
    assert offered is not None
    assert offered.attrib == {
        "codebase": signed_url,
        "version": "0.1.3",
        "prodversionmin": "116",
    }
    assert no_update is not None
    assert no_update.attrib == {"status": "noupdate"}

