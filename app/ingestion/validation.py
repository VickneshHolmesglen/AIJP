import re
from pathlib import PurePosixPath, PureWindowsPath

from app.ingestion.errors import (
    FileTooLargeError,
    InvalidDocumentError,
    UnsupportedFileTypeError,
)

ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "pdf",
    ".txt": "txt",
    ".md": "md",
    ".py": "py",
    ".gd": "gd",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
}
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_filename(raw: str) -> str:
    """Strip directories and control characters; the result is safe to store and display."""
    name = PureWindowsPath(raw).name or PurePosixPath(raw).name
    name = _CONTROL_CHARS.sub("", name).strip().strip(".")
    return name[:255]


def sanitize_source_path(raw: str) -> str:
    """Normalise a project-relative path for citations. Rejects absolute paths and traversal."""
    cleaned = _CONTROL_CHARS.sub("", raw.replace("\\", "/")).strip()
    parts = [p for p in cleaned.split("/") if p not in ("", ".")]
    if cleaned.startswith("/") or re.match(r"^[A-Za-z]:", cleaned) or ".." in parts:
        raise InvalidDocumentError("source_path must be a relative path without '..'")
    if not parts:
        raise InvalidDocumentError("source_path is empty")
    return "/".join(parts)[:1024]


def detect_file_type(filename: str) -> str:
    suffix = PurePosixPath(filename.lower()).suffix
    try:
        return ALLOWED_EXTENSIONS[suffix]
    except KeyError:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{suffix}'. Allowed: {allowed}"
        ) from None


def validate_upload(filename: str, content: bytes, max_bytes: int) -> str:
    """Return the detected file type, or raise an IngestionError."""
    if not filename:
        raise InvalidDocumentError("Filename is empty after sanitisation")
    file_type = detect_file_type(filename)
    if len(content) > max_bytes:
        raise FileTooLargeError(f"File exceeds the {max_bytes} byte limit")
    if not content.strip():
        raise InvalidDocumentError("File is empty")
    # Extension alone is untrusted: check the content matches the claimed type.
    if file_type == "pdf" and not content.lstrip().startswith(b"%PDF-"):
        raise InvalidDocumentError("File does not look like a PDF")
    if file_type != "pdf" and b"\x00" in content:
        raise InvalidDocumentError("Text file contains binary data")
    return file_type
