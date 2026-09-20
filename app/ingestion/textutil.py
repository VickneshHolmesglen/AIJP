from pathlib import PurePosixPath

from app.ingestion.errors import InvalidDocumentError
from app.ingestion.types import Segment


def decode_text(content: bytes) -> str:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidDocumentError("Text file is not valid UTF-8") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def stem(filename: str) -> str:
    return PurePosixPath(filename).stem


def segment_from_lines(
    lines: list[str], first: int, last: int, section: str | None
) -> Segment | None:
    """Segment for 1-based inclusive line range [first, last]; None if it is all whitespace."""
    body = "\n".join(lines[first - 1 : last])
    return Segment(text=body, start_line=first, section=section) if body.strip() else None
