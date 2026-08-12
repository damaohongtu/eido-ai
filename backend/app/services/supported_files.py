"""Central file-extension and MIME policy for uploads and generated artifacts."""
from __future__ import annotations

SUPPORTED_FILE_MEDIA_TYPES = {
    # Documents and ebooks
    ".md": "text/markdown; charset=utf-8",
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".log": "text/plain; charset=utf-8",
    ".rtf": "application/rtf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".epub": "application/epub+zip",
    # Structured data and spreadsheets
    ".csv": "text/csv; charset=utf-8",
    ".tsv": "text/tab-separated-values; charset=utf-8",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".xlsb": "application/vnd.ms-excel.sheet.binary.macroEnabled.12",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".xml": "application/xml",
    ".sql": "application/sql",
    ".parquet": "application/vnd.apache.parquet",
    # Source code and configuration
    ".py": "text/x-python; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".jsx": "text/jsx; charset=utf-8",
    ".ts": "text/typescript; charset=utf-8",
    ".tsx": "text/tsx; charset=utf-8",
    ".java": "text/x-java-source; charset=utf-8",
    ".go": "text/x-go; charset=utf-8",
    ".rs": "text/x-rust; charset=utf-8",
    ".c": "text/x-c; charset=utf-8",
    ".h": "text/x-c; charset=utf-8",
    ".cpp": "text/x-c++; charset=utf-8",
    ".hpp": "text/x-c++; charset=utf-8",
    ".sh": "text/x-shellscript; charset=utf-8",
    ".toml": "application/toml",
    ".ini": "text/plain; charset=utf-8",
    ".conf": "text/plain; charset=utf-8",
    ".properties": "text/plain; charset=utf-8",
    # Browser artifacts and images
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".svg": "image/svg+xml",
    # Archives commonly used to submit a document/data bundle.
    ".zip": "application/zip",
    ".tar": "application/x-tar",
    ".gz": "application/gzip",
    ".tgz": "application/gzip",
    ".7z": "application/x-7z-compressed",
}

SUPPORTED_FILE_EXTENSIONS = frozenset(SUPPORTED_FILE_MEDIA_TYPES)

# These formats should be downloaded unless a dedicated, sandboxed preview is used.
FORCE_ATTACHMENT_FILE_EXTENSIONS = frozenset(
    {
        ".html", ".htm", ".svg", ".xml",
        ".doc", ".docx", ".odt", ".rtf",
        ".ppt", ".pptx", ".odp",
        ".xls", ".xlsx", ".xlsm", ".xlsb", ".ods",
        ".epub", ".zip", ".tar", ".gz", ".tgz", ".7z",
    }
)


def supported_extensions_label() -> str:
    """Return a stable display string for API validation errors."""
    return ", ".join(sorted(SUPPORTED_FILE_EXTENSIONS))
