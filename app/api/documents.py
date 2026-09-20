import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app import services
from app.api.scope import ProjectDep
from app.audit import record_event
from app.auth import EditorDep, ReaderDep, RequireReader
from app.config import Settings, get_settings
from app.db import get_session
from app.ingestion.errors import (
    DuplicateDocumentError,
    FileTooLargeError,
    IngestionError,
    InvalidDocumentError,
    UnsupportedFileTypeError,
)
from app.models import Document
from app.schemas import DocumentDetail, DocumentList, DocumentOut, DocumentSummary

router = APIRouter(prefix="/documents", tags=["documents"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("", response_model=DocumentDetail, status_code=201)
def upload_document(
    session: SessionDep,
    settings: SettingsDep,
    principal: EditorDep,
    project: ProjectDep,
    file: Annotated[
        UploadFile, File(description="PDF, TXT, Markdown, Python, GDScript, JSON or YAML file")
    ],
    source_path: Annotated[
        str | None, Form(description="Project-relative path used in citations")
    ] = None,
) -> DocumentDetail:
    # Read one byte past the limit so oversize files are detected without buffering unbounded data.
    content = file.file.read(settings.max_upload_bytes + 1)
    try:
        document = services.ingest_document(
            session,
            project_id=project.id,
            raw_filename=file.filename or "",
            content=content,
            source_path=source_path,
            settings=settings,
        )
    except DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "Document already ingested", "document_id": str(exc.existing_id)},
        ) from None
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from None
    except FileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except (InvalidDocumentError, IngestionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    record_event(
        session,
        principal,
        "document.upload",
        str(document.id),
        project=project.slug,
        source_path=document.source_path,
        file_type=document.file_type,
        size_bytes=document.size_bytes,
        chunks=len(document.chunks),
    )
    return _detail(document)


@router.get("", response_model=DocumentList, dependencies=[RequireReader])
def list_documents(
    session: SessionDep,
    project: ProjectDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentList:
    rows, total = services.list_documents(session, project.id, limit, offset)
    items = [
        DocumentOut(**DocumentSummary.model_validate(doc).model_dump(), chunk_count=n)
        for doc, n in rows
    ]
    return DocumentList(items=items, total=total, limit=limit, offset=offset)


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: uuid.UUID, session: SessionDep, principal: ReaderDep
) -> DocumentDetail:
    # By id, so the caller's own scope decides (a scoped key sees only its project's documents).
    document = services.get_document(session, document_id, principal.project_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return _detail(document)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: uuid.UUID, session: SessionDep, principal: EditorDep) -> Response:
    document = services.get_document(session, document_id, principal.project_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    source_path = document.source_path  # read before the row is gone
    if not services.delete_document(session, document_id, principal.project_id):
        raise HTTPException(status_code=404, detail="Document not found")
    record_event(session, principal, "document.delete", str(document_id), source_path=source_path)
    return Response(status_code=204)


def _detail(document: Document) -> DocumentDetail:
    summary = DocumentSummary.model_validate(document).model_dump()
    return DocumentDetail.model_validate(
        {**summary, "chunk_count": len(document.chunks), "chunks": document.chunks}
    )
