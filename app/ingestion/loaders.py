"""Text extraction. One loader per file type; add a new format by registering a new loader."""

import io
import re
from collections.abc import Callable

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.ingestion.code_loaders import load_gdscript, load_json, load_python, load_yaml
from app.ingestion.errors import InvalidDocumentError
from app.ingestion.textutil import decode_text, stem
from app.ingestion.types import ExtractedDocument, Segment

Loader = Callable[[bytes, str], ExtractedDocument]

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def load_txt(content: bytes, filename: str) -> ExtractedDocument:
    text = decode_text(content)
    if not text.strip():
        raise InvalidDocumentError("File contains no text")
    return ExtractedDocument(title=stem(filename), segments=[Segment(text=text, start_line=1)])


def load_markdown(content: bytes, filename: str) -> ExtractedDocument:
    """Split on headings so each segment knows its section path (e.g. 'Towers > Poison')."""
    lines = decode_text(content).split("\n")
    segments: list[Segment] = []
    stack: list[tuple[int, str]] = []
    title: str | None = None
    in_fence = False
    buf: list[str] = []
    buf_start = 1
    buf_section: str | None = None

    def flush() -> None:
        if any(line.strip() for line in buf):
            segments.append(Segment("\n".join(buf), start_line=buf_start, section=buf_section))

    for number, line in enumerate(lines, start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(line)
        if match:
            flush()
            level, heading = len(match.group(1)), match.group(2)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading))
            if title is None and level == 1:
                title = heading
            buf, buf_start = [line], number
            buf_section = " > ".join(h for _, h in stack)
        else:
            buf.append(line)
    flush()

    if not segments:
        raise InvalidDocumentError("File contains no text")
    return ExtractedDocument(title=title or stem(filename), segments=segments)


def load_pdf(content: bytes, filename: str) -> ExtractedDocument:
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise InvalidDocumentError("Encrypted PDFs are not supported")
        segments = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n")
            if text.strip():
                segments.append(Segment(text=text, start_line=1, page=page_number))
        meta_title = reader.metadata.title if reader.metadata else None
        page_count = len(reader.pages)
    except PyPdfError as exc:
        raise InvalidDocumentError(f"Could not read PDF: {exc}") from exc
    if not segments:
        raise InvalidDocumentError("PDF has no extractable text (scanned PDFs need OCR)")
    return ExtractedDocument(
        title=(meta_title or "").strip() or stem(filename),
        segments=segments,
        page_count=page_count,
    )


LOADERS: dict[str, Loader] = {
    "txt": load_txt,
    "md": load_markdown,
    "pdf": load_pdf,
    "py": load_python,
    "gd": load_gdscript,
    "json": load_json,
    "yaml": load_yaml,
}


def extract(file_type: str, content: bytes, filename: str) -> ExtractedDocument:
    return LOADERS[file_type](content, filename)
