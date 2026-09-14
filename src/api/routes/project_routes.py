import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.storage.database import get_db
from src.storage.models import Project, AuditLog
from src.storage.filestore import file_store
from src.auth.dependencies import get_current_user
from src.api.schemas import ProjectCreate, ProjectUpdate, ProjectResponse, ProjectListResponse

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED, summary="Create a new project")
async def create_project(
    req: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    project_id = str(uuid.uuid4())
    project = Project(
        id=project_id,
        name=req.name,
        description=req.description or "",
        status="draft"
    )
    db.add(project)
    
    # Audit log
    audit = AuditLog(
        project_id=project_id,
        actor=user.get("sub", "user"),
        action="project_created",
        details={"name": req.name}
    )
    db.add(audit)
    
    await db.commit()
    await db.refresh(project)
    file_store.get_project_dir(project_id)
    return ProjectResponse.model_validate(project)


@router.get("", response_model=ProjectListResponse, summary="List all projects")
async def list_projects(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(select(Project).order_by(Project.created_at.desc()))
    projects = res.scalars().all()
    return ProjectListResponse(
        projects=[ProjectResponse.model_validate(p) for p in projects],
        total=len(projects)
    )


@router.get("/{project_id}", response_model=ProjectResponse, summary="Get project details")
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(select(Project).where(Project.id == project_id))
    project = res.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Project '{project_id}' not found", "details": None}}
        )
    return ProjectResponse.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectResponse, summary="Update project")
async def update_project(
    project_id: str,
    req: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(select(Project).where(Project.id == project_id))
    project = res.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Project '{project_id}' not found", "details": None}}
        )

    if req.name is not None:
        project.name = req.name
    if req.description is not None:
        project.description = req.description
    if req.status is not None:
        project.status = req.status

    db.add(AuditLog(
        project_id=project_id,
        actor=user.get("sub", "user"),
        action="project_updated",
        details=req.model_dump(exclude_unset=True)
    ))

    await db.commit()
    await db.refresh(project)
    return ProjectResponse.model_validate(project)
