"""Ties must be broken by something that survives a re-ingest. Chunk ids are random UUIDs minted at
ingest, so ordering ties by id made lexical and hybrid results a coin flip per ingest (M23: 9 of
32 v6 lexical ranks changed between two runs that differed only in embeddings).

Every test gives the chunks ids that sort OPPOSITE to their (path, chunk_index) order, so ordering
by id and ordering by location cannot both pass."""

import uuid

import pytest
from sqlalchemy.orm import Session

from app import projects, retrieval
from app.models import Chunk, Document
from tests.fakes import DIM


def unit(i: int) -> list[float]:
    vec = [0.0] * DIM
    vec[i] = 1.0
    return vec


def add(session: Session, project_id, path: str, chunks: list[tuple[int, str, str, int]]) -> None:
    """chunks: (chunk_index, id hex digit, content, embedding axis)."""
    doc = Document(
        project_id=project_id,
        filename=path.rsplit("/", 1)[-1],
        source_path=path,
        file_type="md",
        size_bytes=1,
        sha256=uuid.uuid4().hex * 2,
    )
    session.add(doc)
    session.flush()
    for index, digit, content, axis in chunks:
        session.add(
            Chunk(
                id=uuid.UUID(digit * 32),
                document_id=doc.id,
                chunk_index=index,
                content=content,
                embedding=unit(axis),
            )
        )
    session.commit()


@pytest.fixture
def session(client, db_engine):  # `client` wipes the tables first
    with Session(db_engine) as s:
        yield s


def located(hits) -> list[tuple[str, int]]:
    return [(h.document.source_path, h.chunk.chunk_index) for h in hits]


@pytest.mark.integration
def test_lexical_ties_are_ordered_by_path_then_chunk_index_not_by_random_id(session):
    pid = projects.get_or_create_default(session).id
    same = "Poison deals damage over time."  # identical text => identical ts_rank_cd
    add(session, pid, "c.md", [(0, "0", same, 0)])
    add(session, pid, "a.md", [(1, "1", same, 1), (0, "f", same, 2)])
    add(session, pid, "b.md", [(0, "8", same, 3)])
    hits = retrieval.lexical_search(session, "poison", None, 10, project_id=pid)
    assert located(hits) == [("a.md", 0), ("a.md", 1), ("b.md", 0), ("c.md", 0)]


@pytest.mark.integration
def test_hybrid_rrf_ties_are_ordered_by_location_not_by_random_id(session):
    pid = projects.get_or_create_default(session).id
    # pool=1: b.md is the only vector hit and a.md the only lexical hit, both at rank 1, so both
    # fuse to exactly 1/(k+1): a genuine RRF tie.
    add(session, pid, "b.md", [(0, "0", "Nothing relevant here.", 0)])
    add(session, pid, "a.md", [(0, "f", "Poison deals damage over time.", 5)])
    hits = retrieval.hybrid_search(
        session, "poison", unit(0), top_k=2, pool=1, rrf_k=60, project_id=pid
    )
    assert hits[0].score == hits[1].score
    assert located(hits) == [("a.md", 0), ("b.md", 0)]
