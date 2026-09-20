"""Line-aware chunking.

Chunks are built from whole lines so every chunk maps to an exact line range, which is what
citations like "design/towers.md, lines 12-30" need. A chunk never crosses a segment boundary,
so it inherits exactly one page / section. Consecutive chunks within a segment overlap by a few
lines so a fact split across a boundary is still retrievable.
"""

from collections.abc import Iterable, Iterator

from app.ingestion.types import ChunkDraft, Segment

_Line = tuple[int, str, bool]  # (line number, text, is_new_content_not_overlap)


def _split_long_line(number: int, text: str, max_chars: int) -> Iterator[tuple[int, str]]:
    for start in range(0, len(text), max_chars):
        yield number, text[start : start + max_chars]


def _emit(lines: list[_Line], segment: Segment, index: int) -> ChunkDraft | None:
    body = "\n".join(text for _, text, _ in lines).strip()
    if not body:
        return None
    non_blank = [n for n, text, _ in lines if text.strip()]
    return ChunkDraft(
        chunk_index=index,
        content=body,
        section=segment.section,
        page=segment.page,
        start_line=non_blank[0],
        end_line=non_blank[-1],
    )


def _overlap_tail(lines: list[_Line], overlap_chars: int) -> list[_Line]:
    tail: list[_Line] = []
    size = 0
    for number, text, _ in reversed(lines[1:]):  # never carry the whole chunk forward
        if size + len(text) + 1 > overlap_chars:
            break
        tail.append((number, text, False))
        size += len(text) + 1
    tail.reverse()
    return tail


def chunk_segments(
    segments: Iterable[Segment], max_chars: int, overlap_chars: int
) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    for segment in segments:
        numbered: list[tuple[int, str]] = []
        for offset, line in enumerate(segment.text.split("\n")):
            number = segment.start_line + offset
            if len(line) > max_chars:
                numbered.extend(_split_long_line(number, line, max_chars))
            else:
                numbered.append((number, line))

        current: list[_Line] = []
        size = 0
        for number, text in numbered:
            has_new = any(is_new for _, _, is_new in current)
            if current and has_new and size + len(text) + 1 > max_chars:
                if chunk := _emit(current, segment, len(chunks)):
                    chunks.append(chunk)
                current = _overlap_tail(current, overlap_chars)
                size = sum(len(t) + 1 for _, t, _ in current)
            current.append((number, text, True))
            size += len(text) + 1
        if any(is_new for _, _, is_new in current) and (
            chunk := _emit(current, segment, len(chunks))
        ):
            chunks.append(chunk)
    return chunks
