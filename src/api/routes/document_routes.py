import os
import uuid
import hashlib
from pathlib import Path
from typing import List
from fastapi import (
    APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from config.settings import settings
import src.storage.database as db_module
from src.storage.models import Project, Document, DocumentSection, AuditLog
from src.storage.filestore import file_store
from src.auth.dependencies import get_current_user
from src.ingestion.pipeline import ingestion_pipeline
from src.api.schemas import (
    DocumentUploadResponse, DocumentStatusResponse,
    DocumentOutlineResponse, DocumentSectionItem
)

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["Documents"])


async def _run_async_ingestion(project_id: str, document_id: str, file_path: Path):
    async with db_module.AsyncSessionLocal() as session:
        await ingestion_pipeline.process_document(
            project_id=project_id,
            document_id=document_id,
            file_path=file_path,
            db=session
        )


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload and ingest a project document"
)
async def upload_document(
    project_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    # Verify project exists
    p_res = await db.execute(select(Project).where(Project.id == project_id))
    project = p_res.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Project '{project_id}' not found", "details": None}}
        )

    # Validate file extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"error": {
                "code": "UNSUPPORTED_MEDIA_TYPE",
                "message": f"Unsupported file extension '{ext}'. Allowed: {settings.ALLOWED_EXTENSIONS}",
                "details": None
            }}
        )

    # Read content & check size limit
    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"error": {
                "code": "FILE_TOO_LARGE",
                "message": f"File exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB}MB",
                "details": None
            }}
        )

    # Content Hash Dedup check (Idempotent upload)
    content_hash = hashlib.sha256(content).hexdigest()
    d_res = await db.execute(
        select(Document).where(Document.project_id == project_id, Document.content_hash == content_hash)
    )
    existing_doc = d_res.scalar_one_or_none()
    if existing_doc:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "document_id": existing_doc.id,
                "project_id": project_id,
                "filename": existing_doc.filename,
                "status": existing_doc.status,
                "file_size_bytes": existing_doc.file_size_bytes,
                "content_hash": existing_doc.content_hash,
                "status_url": f"/projects/{project_id}/documents/{existing_doc.id}"
            }
        )

    # Save to project file store
    document_id = str(uuid.uuid4())
    saved_path = await file_store.save_upload(
        project_id=project_id,
        document_id=document_id,
        filename=file.filename or f"doc{ext}",
        content=content
    )

    doc = Document(
        id=document_id,
        project_id=project_id,
        filename=file.filename or f"doc{ext}",
        content_type=file.content_type or "application/octet-stream",
        file_path=str(saved_path),
        file_size_bytes=len(content),
        content_hash=content_hash,
        status="pending"
    )
    db.add(doc)

    db.add(AuditLog(
        project_id=project_id,
        actor=user.get("sub", "user"),
        action="document_uploaded",
        details={"document_id": document_id, "filename": file.filename}
    ))

    await db.commit()
    await db.refresh(doc)

    # Launch background parsing task
    background_tasks.add_task(_run_async_ingestion, project_id, document_id, saved_path)

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "document_id": document_id,
            "project_id": project_id,
            "filename": doc.filename,
            "status": "pending",
            "file_size_bytes": doc.file_size_bytes,
            "content_hash": doc.content_hash,
            "status_url": f"/projects/{project_id}/documents/{document_id}"
        }
    )


@router.get(
    "/{document_id}",
    response_model=DocumentStatusResponse,
    summary="Get document parse status"
)
async def get_document_status(
    project_id: str,
    document_id: str,
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(
        select(Document).where(Document.id == document_id, Document.project_id == project_id)
    )
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Document '{document_id}' not found in project '{project_id}'", "details": None}}
        )
    return DocumentStatusResponse.model_validate(doc)


@router.get(
    "/{document_id}/sections",
    response_model=DocumentOutlineResponse,
    summary="Get structured document outline and sections"
)
async def get_document_sections(
    project_id: str,
    document_id: str,
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    d_res = await db.execute(
        select(Document).where(Document.id == document_id, Document.project_id == project_id)
    )
    doc = d_res.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Document '{document_id}' not found in project '{project_id}'", "details": None}}
        )

    s_res = await db.execute(
        select(DocumentSection)
        .where(DocumentSection.document_id == document_id, DocumentSection.project_id == project_id)
        .order_by(DocumentSection.created_at.asc())
    )
    sections = s_res.scalars().all()

    section_items = [
        DocumentSectionItem(
            section_id=s.section_id,
            title=s.title,
            level=s.level,
            page_number=s.page_number,
            chunk_index=s.chunk_index
        ) for s in sections
    ]

    return DocumentOutlineResponse.model_validate({
        "document_id": document_id,
        "project_id": project_id,
        "filename": doc.filename,
        "total_sections": len(section_items),
        "sections": section_items
    })
