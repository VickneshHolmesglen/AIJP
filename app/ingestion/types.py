from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    """A run of text with shared provenance, produced by a loader.

    `start_line` is the 1-based line number of the first line of `text` in the source
    (page-relative for PDFs, where `page` is also set).
    """

    text: str
    start_line: int = 1
    page: int | None = None
    section: str | None = None


@dataclass(frozen=True)
class ExtractedDocument:
    title: str | None
    segments: list[Segment]
    page_count: int | None = None


@dataclass(frozen=True)
class ChunkDraft:
    chunk_index: int
    content: str
    section: str | None = None
    page: int | None = None
    start_line: int | None = None
    end_line: int | None = None
