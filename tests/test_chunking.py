from app.ingestion.chunking import chunk_segments
from app.ingestion.types import Segment


def _numbered(n: int) -> str:
    return "\n".join(f"line {i} " + "x" * 30 for i in range(1, n + 1))


def test_short_segment_is_one_chunk_with_line_range():
    chunks = chunk_segments([Segment("alpha\nbeta\ngamma", start_line=10)], 500, 50)
    assert len(chunks) == 1
    assert (chunks[0].start_line, chunks[0].end_line) == (10, 12)
    assert chunks[0].chunk_index == 0


def test_long_segment_splits_and_every_line_is_covered():
    text = _numbered(60)
    chunks = chunk_segments([Segment(text)], max_chars=300, overlap_chars=60)
    assert len(chunks) > 1
    covered = set()
    for c in chunks:
        assert c.start_line is not None and c.end_line is not None
        assert len(c.content) <= 300
        covered.update(range(c.start_line, c.end_line + 1))
    assert covered == set(range(1, 61))
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunks_overlap_but_always_advance():
    chunks = chunk_segments([Segment(_numbered(60))], max_chars=300, overlap_chars=80)
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        assert nxt.start_line <= prev.end_line + 1  # no gap
        assert nxt.end_line > prev.end_line  # progress


def test_zero_overlap_produces_disjoint_chunks():
    chunks = chunk_segments([Segment(_numbered(40))], max_chars=300, overlap_chars=0)
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        assert nxt.start_line == prev.end_line + 1


def test_provenance_is_inherited_from_segment():
    seg = Segment("some text", start_line=5, page=3, section="A > B")
    (chunk,) = chunk_segments([seg], 500, 50)
    assert (chunk.page, chunk.section) == (3, "A > B")


def test_chunks_never_cross_segment_boundaries():
    segs = [Segment("one", section="S1"), Segment("two", section="S2")]
    chunks = chunk_segments(segs, 500, 50)
    assert [(c.content, c.section) for c in chunks] == [("one", "S1"), ("two", "S2")]
    assert [c.chunk_index for c in chunks] == [0, 1]


def test_single_overlong_line_is_hard_split():
    chunks = chunk_segments([Segment("y" * 1000)], max_chars=300, overlap_chars=0)
    assert len(chunks) == 4
    assert all(len(c.content) <= 300 for c in chunks)
    assert {c.start_line for c in chunks} == {1}


def test_blank_only_segment_yields_nothing():
    assert chunk_segments([Segment("\n\n  \n")], 500, 50) == []
