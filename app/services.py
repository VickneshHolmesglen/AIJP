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


def _existing(session: Session, project_id: uuid.UUID, digest: str) -> uuid.UUID | None:
    """The document with these exact bytes IN THIS PROJECT (the same file may live in another)."""
    return session.scalar(
        select(Document.id).where(Document.project_id == project_id, Document.sha256 == digest)
    )


def ingest_document(
    session: Session,
    *,
    project_id: uuid.UUID,
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
    existing = _existing(session, project_id, digest)
    if existing:
        raise DuplicateDocumentError(existing)

    extracted = extract(file_type, content, filename)
    drafts = chunk_segments(
        extracted.segments, settings.chunk_max_chars, settings.chunk_overlap_chars
    )

    document = Document(
        project_id=project_id,
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
        existing = _existing(session, project_id, digest)
        raise DuplicateDocumentError(existing) from None
    return document


def embed_pending_chunks(
    session: Session,
    provider: EmbeddingProvider,
    batch_size: int,
    document_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
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
        if project_id is not None:
            query = query.join(Document, Document.id == Chunk.document_id).where(
                Document.project_id == project_id
            )
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
    session: Session, project_id: uuid.UUID | None, limit: int, offset: int
) -> tuple[list[tuple[Document, int]], int]:
    """Return ((document, chunk_count) rows, total) for one project (None: every project)."""
    in_scope = [] if project_id is None else [Document.project_id == project_id]
    counts = (
        select(Chunk.document_id, func.count().label("n")).group_by(Chunk.document_id).subquery()
    )
    rows = session.execute(
        select(Document, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.document_id == Document.id)
        .where(*in_scope)
        .order_by(Document.created_at.desc(), Document.id)
        .limit(limit)
        .offset(offset)
    ).all()
    total = session.scalar(select(func.count()).select_from(Document).where(*in_scope)) or 0
    return [(doc, int(n)) for doc, n in rows], total


def get_document(
    session: Session, document_id: uuid.UUID, project_id: uuid.UUID | None
) -> Document | None:
    """The document, or None if it does not exist OR is outside `project_id` (None: any project).
    A document in someone else's project is indistinguishable from one that does not exist."""
    document = session.get(Document, document_id)
    if document is None or (project_id is not None and document.project_id != project_id):
        return None
    return document


def chunk_count(session: Session, document_id: uuid.UUID) -> int:
    return session.scalar(select(func.count()).where(Chunk.document_id == document_id)) or 0


def delete_document(session: Session, document_id: uuid.UUID, project_id: uuid.UUID | None) -> bool:
    document = get_document(session, document_id, project_id)
    if document is None:
        return False
    session.delete(document)
    session.commit()
    return True
