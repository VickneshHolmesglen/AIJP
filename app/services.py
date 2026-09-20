import hashlib
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.embeddings import EmbeddingProvider
from app.ingestion.chunking import chunk_segments
from app.ingestion.errors import DuplicateDocumentError
from app.ingestion.loaders import extract
from app.ingestion.validation import sanitize_filename, sanitize_source_path, validate_upload
from app.models import Chunk, Document


def ingest_document(
    session: Session,
    *,
    raw_filename: str,
    content: bytes,
    source_path: str | None,
    settings: Settings,
) -> Document:
    """Validate -> extract -> chunk -> persist. Raises IngestionError subclasses on bad input."""
    filename = sanitize_filename(raw_filename)
    file_type = validate_upload(filename, content, settings.max_upload_bytes)
    citation_path = sanitize_source_path(source_path) if source_path else filename

    digest = hashlib.sha256(content).hexdigest()
    existing = session.scalar(select(Document.id).where(Document.sha256 == digest))
    if existing:
        raise DuplicateDocumentError(existing)

    extracted = extract(file_type, content, filename)
    drafts = chunk_segments(
        extracted.segments, settings.chunk_max_chars, settings.chunk_overlap_chars
    )

    document = Document(
        filename=filename,
        source_path=citation_path,
        file_type=file_type,
        size_bytes=len(content),
        sha256=digest,
        title=extracted.title,
        page_count=extracted.page_count,
        chunks=[
            Chunk(
                chunk_index=d.chunk_index,
                content=d.content,
                section=d.section,
                page=d.page,
                start_line=d.start_line,
                end_line=d.end_line,
            )
            for d in drafts
        ],
    )
    session.add(document)
    try:
        session.commit()
    except IntegrityError:
        # Lost a race with a concurrent upload of the same bytes.
        session.rollback()
        existing = session.scalar(select(Document.id).where(Document.sha256 == digest))
        raise DuplicateDocumentError(existing) from None
    return document


def embed_pending_chunks(
    session: Session,
    provider: EmbeddingProvider,
    batch_size: int,
    document_id: uuid.UUID | None = None,
) -> int:
    """Embed chunks that have no vector yet. Returns how many were embedded.

    Commits per batch, so a provider failure midway keeps earlier batches and a retry only
    redoes the remainder.
    """
    embedded = 0
    while True:
        query = select(Chunk).where(Chunk.embedding.is_(None))
        if document_id is not None:
            query = query.where(Chunk.document_id == document_id)
        batch = list(
            session.scalars(query.order_by(Chunk.document_id, Chunk.chunk_index).limit(batch_size))
        )
        if not batch:
            return embedded
        vectors = provider.embed([c.content for c in batch])
        for chunk, vector in zip(batch, vectors, strict=True):
            chunk.embedding = vector
        session.commit()
        embedded += len(batch)


def list_documents(
    session: Session, limit: int, offset: int
) -> tuple[list[tuple[Document, int]], int]:
    """Return ((document, chunk_count) rows, total)."""
    counts = (
        select(Chunk.document_id, func.count().label("n")).group_by(Chunk.document_id).subquery()
    )
    rows = session.execute(
        select(Document, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.document_id == Document.id)
        .order_by(Document.created_at.desc(), Document.id)
        .limit(limit)
        .offset(offset)
    ).all()
    total = session.scalar(select(func.count()).select_from(Document)) or 0
    return [(doc, int(n)) for doc, n in rows], total


def get_document(session: Session, document_id: uuid.UUID) -> Document | None:
    return session.get(Document, document_id)


def chunk_count(session: Session, document_id: uuid.UUID) -> int:
    return session.scalar(select(func.count()).where(Chunk.document_id == document_id)) or 0


def delete_document(session: Session, document_id: uuid.UUID) -> bool:
    document = session.get(Document, document_id)
    if document is None:
        return False
    session.delete(document)
    session.commit()
    return True
