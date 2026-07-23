"""Shared response policy for browser previews of user-controlled files."""

from __future__ import annotations

from collections.abc import Collection

# These formats can execute or otherwise load active same-origin content when a
# browser navigates to them.  They remain attachments by default and are only
# rendered inline for an explicit, sandboxed preview request.
ACTIVE_PREVIEW_EXTENSIONS = frozenset(
    {
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
    }
)

ACTIVE_PREVIEW_MEDIA_TYPES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "image/svg+xml",
        "application/xml",
        "text/xml",
        "message/rfc822",
        "multipart/related",
        "application/x-mimearchive",
    }
)

# A response-level policy is required because preview URLs can also be opened
# directly in a new tab, where an iframe's sandbox attribute would not apply.
# No sandbox capability tokens are granted: in particular, scripts and
# same-origin access stay disabled.  Static inline styles and embedded images
# are sufficient for useful report/SVG previews without allowing network I/O.
ACTIVE_PREVIEW_CSP = "; ".join(
    (
        "sandbox",
        "default-src 'none'",
        "script-src 'none'",
        "connect-src 'none'",
        "form-action 'none'",
        "object-src 'none'",
        "frame-src 'none'",
        "child-src 'none'",
        "worker-src 'none'",
        "base-uri 'none'",
        "img-src data: blob:",
        "style-src 'unsafe-inline'",
        "font-src data:",
        "media-src data: blob:",
        "frame-ancestors 'self'",
    )
)


def is_active_preview_content(extension: str, media_type: str | None = None) -> bool:
    """Identify browser-active documents by both suffix and final response MIME."""
    normalized_type = (media_type or "").partition(";")[0].strip().lower()
    return (
        extension.lower() in ACTIVE_PREVIEW_EXTENSIONS
        or normalized_type in ACTIVE_PREVIEW_MEDIA_TYPES
        or normalized_type.endswith("+xml")
    )


def file_content_disposition(
    extension: str,
    *,
    download: bool,
    preview: bool,
    force_attachment_extensions: Collection[str],
    media_type: str | None = None,
) -> str:
    """Choose a disposition without weakening the ordinary download policy."""
    normalized = extension.lower()
    if download:
        return "attachment"
    if is_active_preview_content(normalized, media_type):
        return "inline" if preview else "attachment"
    if normalized in force_attachment_extensions:
        return "attachment"
    return "inline"


def file_response_security_headers(
    extension: str,
    *,
    download: bool,
    preview: bool,
    media_type: str | None = None,
) -> dict[str, str]:
    """Return response headers for a file, adding CSP only to active previews."""
    headers = {"X-Content-Type-Options": "nosniff"}
    if preview and not download and is_active_preview_content(extension, media_type):
        headers.update(
            {
                "Content-Security-Policy": ACTIVE_PREVIEW_CSP,
                "Cache-Control": "private, no-store",
                "Referrer-Policy": "no-referrer",
            }
        )
    return headers
