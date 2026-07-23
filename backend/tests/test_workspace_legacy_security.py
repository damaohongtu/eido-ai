"""The legacy no-session file endpoint must never expose repository files."""

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.workspace import (
    _content_disposition_type,
    _resolve_global_path,
)


@pytest.mark.parametrize("path", [".env", "backend/app/main.py", ".claude/skills"])
def test_legacy_global_path_rejects_source_configuration_and_skills(path: str):
    with pytest.raises(HTTPException) as exc_info:
        _resolve_global_path(path)

    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("path", ["uploads/old.pdf", "output/old.csv", "outputs/old.md"])
def test_legacy_global_path_only_allows_historical_file_roots(path: str):
    resolved = _resolve_global_path(path)

    assert resolved.name.startswith("old.")


@pytest.mark.parametrize(
    "extension",
    [
        ".html",
        ".htm",
        ".xht",
        ".xhtml",
        ".svg",
        ".svgz",
        ".xml",
        ".xsl",
        ".xslt",
        ".mhtml",
        ".mht",
    ],
)
def test_workspace_active_content_is_always_an_attachment(extension: str):
    assert _content_disposition_type(extension, download=False) == "attachment"


@pytest.mark.parametrize(
    "extension",
    [
        ".html",
        ".htm",
        ".xht",
        ".xhtml",
        ".svg",
        ".svgz",
        ".xml",
        ".xsl",
        ".xslt",
        ".mhtml",
        ".mht",
    ],
)
def test_workspace_active_content_requires_explicit_preview_for_inline(
    extension: str,
):
    assert _content_disposition_type(extension, download=False, preview=True) == "inline"
    assert _content_disposition_type(extension, download=True, preview=True) == "attachment"


def test_workspace_safe_content_respects_explicit_download():
    assert _content_disposition_type(".png", download=False) == "inline"
    assert _content_disposition_type(".png", download=True) == "attachment"


@pytest.mark.parametrize(
    "media_type",
    ["text/html; charset=utf-8", "application/xhtml+xml", "application/atom+xml"],
)
def test_workspace_active_media_type_cannot_bypass_suffix_policy(media_type: str):
    assert (
        _content_disposition_type(".data", download=False, media_type=media_type)
        == "attachment"
    )
    assert (
        _content_disposition_type(
            ".data", download=False, preview=True, media_type=media_type
        )
        == "inline"
    )
