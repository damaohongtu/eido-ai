"""Shared response policy for browser previews of user-controlled files."""

from __future__ import annotations

import html
from collections.abc import Collection
from pathlib import Path

from fastapi.responses import HTMLResponse
from markdown_it import MarkdownIt

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
# same-origin access stays disabled.  Scripts are allowed inside the opaque
# sandbox so generated interactive reports can initialize charts, while
# connect/form/object/frame capabilities remain blocked.
ACTIVE_PREVIEW_CSP = "; ".join(
    (
        "sandbox allow-scripts",
        "default-src 'none'",
        "script-src 'unsafe-inline' https:",
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

MARKDOWN_PREVIEW_CSP = "; ".join(
    (
        "sandbox",
        "default-src 'none'",
        "script-src 'none'",
        "connect-src 'none'",
        "form-action 'none'",
        "object-src 'none'",
        "frame-src 'none'",
        "base-uri 'none'",
        "img-src data:",
        "style-src 'unsafe-inline'",
        "font-src data:",
        "frame-ancestors 'self'",
    )
)

_MARKDOWN = MarkdownIt(
    "commonmark",
    {"html": False, "linkify": False, "typographer": False},
).enable(["table", "strikethrough"])

_MARKDOWN_PREVIEW_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #f8fafc; color: #1f2937; font: 16px/1.7 -apple-system,
  BlinkMacSystemFont, "Segoe UI", sans-serif; overflow-wrap: anywhere; }
main { width: min(920px, calc(100% - 32px)); margin: 24px auto; padding: 32px 40px;
  background: white; border: 1px solid #e5e7eb; border-radius: 16px;
  box-shadow: 0 8px 30px rgba(15, 23, 42, .06); }
h1, h2, h3, h4, h5, h6 { line-height: 1.3; color: #111827; margin: 1.5em 0 .6em; }
h1 { margin-top: 0; padding-bottom: .35em; border-bottom: 1px solid #e5e7eb; }
a { color: #2563eb; text-decoration: underline; text-underline-offset: 2px; }
blockquote { margin: 1em 0; padding: .2em 1em; color: #4b5563; border-left: 4px solid #d1d5db; }
code { padding: .15em .35em; background: #f3f4f6; border-radius: 5px;
  font: .9em/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }
pre { max-width: 100%; padding: 16px; overflow-x: auto; background: #111827; color: #f9fafb;
  border-radius: 10px; white-space: pre; }
pre code { padding: 0; background: transparent; color: inherit; }
table { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; }
th, td { padding: 8px 12px; border: 1px solid #d1d5db; text-align: left; }
th { background: #f3f4f6; }
img { max-width: 100%; height: auto; }
hr { margin: 2em 0; border: 0; border-top: 1px solid #e5e7eb; }
@media (max-width: 640px) { main { width: 100%; margin: 0; padding: 20px; border: 0; border-radius: 0; } }
"""


def markdown_preview_response(path: Path, display_name: str | None = None) -> HTMLResponse:
    """Render Markdown as inert HTML for an explicit authenticated preview."""
    source = path.read_text(encoding="utf-8", errors="replace")
    rendered = _MARKDOWN.render(source)
    title = html.escape(display_name or path.name)
    document = (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title><style>{_MARKDOWN_PREVIEW_STYLE}</style>"
        f"</head><body><main>{rendered}</main></body></html>"
    )
    return HTMLResponse(
        document,
        headers={
            "Content-Security-Policy": MARKDOWN_PREVIEW_CSP,
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
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
