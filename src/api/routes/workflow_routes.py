import os
import uuid
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Header, Response, Request
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from pydantic import BaseModel, Field
from config.settings import settings
import src.storage.database as db_module
from src.storage.models import Project, Run, Usage, RunEvent, Task
from src.storage.filestore import file_store
from src.auth.dependencies import get_current_user
from src.observability.events import event_hub
from src.workflows.runner import workflow_runner
from src.workflows.planning.dag import validate_task_dag, split_task
from src.api.schemas import ErrorEnvelope, CodegenTriggerRequest

logger = logging.getLogger("workflow_routes")
router = APIRouter(prefix="/projects/{project_id}", tags=["Workflows & Runs"])


class TriggerRequirementsRequest(BaseModel):
    document_ids: Optional[List[str]] = Field(
        default_factory=list,
        description="List of document IDs to process in Workflow 1",
        examples=[["doc-uuid-123", "doc-uuid-456"]]
    )


class TriggerPlanningRequest(BaseModel):
    requirements_run_id: Optional[str] = Field(
        default=None,
        description="Completed requirements run ID from Workflow 1 to base the planning on",
        examples=["req-run-uuid-789"]
    )
    requirements_doc: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional direct requirements specification JSON (if omitted, loaded from requirements_run_id)"
    )


class TaskPatchRequest(BaseModel):
    action: Optional[str] = Field(
        default="edit",
        description="Action to perform: 'edit', 'split', or 'reorder'"
    )
    title: Optional[str] = Field(default=None, description="Updated task title")
    description: Optional[str] = Field(default=None, description="Updated description")
    target_files: Optional[List[str]] = Field(default=None, description="Target files to create or modify")
    acceptance_criteria: Optional[List[str]] = Field(default=None, description="Measurable pass/fail criteria")
    dependencies: Optional[List[str]] = Field(default=None, description="Task IDs this task strictly depends on")
    pattern_refs: Optional[List[str]] = Field(default=None, description="Agentic design patterns guiding this task")
    split_into: Optional[List[Dict[str, Any]]] = Field(default=None, description="List of subtasks when action is 'split'")
    order: Optional[List[str]] = Field(default=None, description="List of task IDs when action is 'reorder'")


# ==========================================
# 1. Trigger Requirements Workflow
# ==========================================
@router.post(
    "/workflows/requirements",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Workflow 1: Requirements Gathering Agent"
)
async def trigger_requirements_workflow(
    project_id: str,
    body: Optional[TriggerRequirementsRequest] = None,
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    # Verify project
    p_res = await db.execute(select(Project).where(Project.id == project_id))
    project = p_res.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Project '{project_id}' not found", "details": None}}
        )

    # Idempotency / Single Active Run Check (409 Conflict)
    active_res = await db.execute(
        select(Run).where(
            Run.project_id == project_id,
            Run.status.in_(["pending", "running", "paused"])
        )
    )
    active_run = active_res.scalar_one_or_none()
    if active_run:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": {
                "code": "RUN_ALREADY_ACTIVE",
                "message": f"Run '{active_run.id}' is already active for project '{project_id}'",
                "details": {"active_run_id": active_run.id, "status": active_run.status}
            }}
        )

    document_ids = []
    if body:
        if hasattr(body, "document_ids"):
            document_ids = body.document_ids or []
        elif isinstance(body, dict):
            document_ids = body.get("document_ids", [])
    run_id = str(uuid.uuid4())

    new_run = Run(
        id=run_id,
        project_id=project_id,
        workflow_name="requirements",
        status="pending",
        current_node="START",
        input_data={"document_ids": document_ids}
    )
    db.add(new_run)
    await db.commit()
    await db.refresh(new_run)

    # Start background execution
    await workflow_runner.start_requirements_run(project_id, run_id, document_ids)

    return Response(
        status_code=status.HTTP_202_ACCEPTED,
        content=json.dumps({
            "run_id": run_id,
            "project_id": project_id,
            "workflow": "requirements",
            "status": "pending",
            "location": f"/projects/{project_id}/runs/{run_id}",
            "events_url": f"/projects/{project_id}/runs/{run_id}/events",
            "hitl_ws_url": f"/projects/{project_id}/runs/{run_id}/hitl"
        }),
        headers={
            "Location": f"/projects/{project_id}/runs/{run_id}",
            "Content-Type": "application/json"
        }
    )


# ==========================================
# 1B. Trigger Planning Workflow
# ==========================================
@router.post(
    "/workflows/planning",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Workflow 2: Combined Project & Code Planning Multi-Agent Graph"
)
async def trigger_planning_workflow(
    project_id: str,
    body: Optional[TriggerPlanningRequest] = None,
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    # Verify project
    p_res = await db.execute(select(Project).where(Project.id == project_id))
    project = p_res.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Project '{project_id}' not found", "details": None}}
        )

    # Idempotency / Single Active Run Check (409 Conflict)
    active_res = await db.execute(
        select(Run).where(
            Run.project_id == project_id,
            Run.status.in_(["pending", "running", "paused"])
        )
    )
    active_run = active_res.scalar_one_or_none()
    if active_run:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": {
                "code": "RUN_ALREADY_ACTIVE",
                "message": f"Run '{active_run.id}' is already active for project '{project_id}'",
                "details": {"active_run_id": active_run.id, "status": active_run.status}
            }}
        )

    requirements_run_id = None
    requirements_doc = None
    if body:
        if hasattr(body, "requirements_run_id"):
            requirements_run_id = body.requirements_run_id
            raw_doc = getattr(body, "requirements_doc", None)
            if raw_doc and isinstance(raw_doc, dict) and raw_doc.get("functional_requirements"):
                requirements_doc = raw_doc
        elif isinstance(body, dict):
            requirements_run_id = body.get("requirements_run_id")
            raw_doc = body.get("requirements_doc")
            if raw_doc and isinstance(raw_doc, dict) and raw_doc.get("functional_requirements"):
                requirements_doc = raw_doc

    # If requirements_doc not passed directly, locate from latest completed requirements run
    if not requirements_doc:
        if requirements_run_id:
            req_stmt = select(Run).where(Run.id == requirements_run_id, Run.project_id == project_id)
        else:
            req_stmt = (
                select(Run)
                .where(
                    Run.project_id == project_id,
                    Run.workflow_name == "requirements",
                    Run.status == "completed"
                )
                .order_by(Run.completed_at.desc())
            )
        req_res = await db.execute(req_stmt)
        req_run = req_res.scalar_one_or_none()
        if not req_run:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": {
                    "code": "REQUIREMENTS_NOT_FOUND",
                    "message": "No approved requirements run found. Please execute and approve Workflow 1 first.",
                    "details": None
                }}
            )
        requirements_run_id = req_run.id
        runs_dir = file_store.get_runs_dir(project_id, requirements_run_id)
        req_file = runs_dir / "requirements.json"
        if req_file.exists():
            try:
                with open(req_file, "r", encoding="utf-8") as f:
                    requirements_doc = json.load(f)
            except Exception:
                pass
        if not requirements_doc and req_run.output_data:
            requirements_doc = req_run.output_data.get("requirements_json")

    if not requirements_doc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {
                "code": "INVALID_REQUIREMENTS",
                "message": "Could not load requirements specification for planning.",
                "details": None
            }}
        )

    run_id = str(uuid.uuid4())
    new_run = Run(
        id=run_id,
        project_id=project_id,
        workflow_name="planning",
        status="pending",
        current_node="START",
        input_data={"requirements_run_id": requirements_run_id}
    )
    db.add(new_run)
    await db.commit()
    await db.refresh(new_run)

    # Start background execution
    await workflow_runner.start_planning_run(
        project_id=project_id,
        run_id=run_id,
        requirements_doc=requirements_doc,
        requirements_run_id=requirements_run_id
    )

    return Response(
        status_code=status.HTTP_202_ACCEPTED,
        content=json.dumps({
            "run_id": run_id,
            "project_id": project_id,
            "workflow": "planning",
            "status": "pending",
            "location": f"/projects/{project_id}/runs/{run_id}",
            "events_url": f"/projects/{project_id}/runs/{run_id}/events",
            "hitl_ws_url": f"/projects/{project_id}/runs/{run_id}/hitl"
        }),
        headers={
            "Location": f"/projects/{project_id}/runs/{run_id}",
            "Content-Type": "application/json"
        }
    )


@router.post(
    "/workflows/codegen",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Workflow 3: Code Generation"
)
async def trigger_codegen_workflow(
    project_id: str,
    body: Optional[CodegenTriggerRequest] = None,
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

    # 1. In-memory lock: verify no active codegen run is running for this project
    active_stmt = select(Run).where(
        Run.project_id == project_id,
        Run.workflow_name == "codegen",
        Run.status.in_(["pending", "running", "paused"])
    )
    active_res = await db.execute(active_stmt)
    active_run = active_res.scalar_one_or_none()
    if active_run:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": {
                "code": "CODEGEN_ALREADY_ACTIVE",
                "message": f"A codegen run is already active for project '{project_id}' (Run ID: {active_run.id}, Status: {active_run.status}).",
                "details": {"active_run_id": active_run.id, "status": active_run.status}
            }}
        )

    # 2. Extract payload (supporting JSON body, dict, or Pydantic model)
    raw_body = None
    if isinstance(body, CodegenTriggerRequest):
        raw_body = body.model_dump(exclude_unset=True)
    elif isinstance(body, dict):
        raw_body = body

    planning_run_id = None
    if raw_body and isinstance(raw_body, dict):
        planning_run_id = raw_body.get("planning_run_id")

    # If not provided, find latest completed planning run
    if not planning_run_id:
        plan_stmt = select(Run).where(
            Run.project_id == project_id,
            Run.workflow_name == "planning",
            Run.status == "completed"
        ).order_by(Run.completed_at.desc())
        plan_res = await db.execute(plan_stmt)
        plan_run = plan_res.scalar_one_or_none()
        if not plan_run:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": {
                    "code": "PLANNING_RUN_NOT_FOUND",
                    "message": "No completed planning run found. Please execute and approve Workflow 2 first.",
                    "details": None
                }}
            )
        planning_run_id = plan_run.id
    else:
        plan_stmt = select(Run).where(Run.id == planning_run_id, Run.project_id == project_id)
        plan_res = await db.execute(plan_stmt)
        plan_run = plan_res.scalar_one_or_none()
        if not plan_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": {
                    "code": "NOT_FOUND",
                    "message": f"Planning run '{planning_run_id}' not found.",
                    "details": None
                }}
            )

    # 3. Load tasks from body (if provided and valid) or DB (or tasks.json)
    tasks_data = []
    if raw_body and isinstance(raw_body, dict) and raw_body.get("tasks"):
        raw_tasks = raw_body.get("tasks")
        if isinstance(raw_tasks, list):
            # Only keep tasks that actually specify an ID or title (avoids [{}] defaults from Swagger UI)
            tasks_data = [t for t in raw_tasks if isinstance(t, dict) and (t.get("task_id") or t.get("title"))]

    if not tasks_data:
        task_stmt = select(Task).where(Task.run_id == planning_run_id).order_by(Task.order_index.asc())
        task_res = await db.execute(task_stmt)
        db_tasks = task_res.scalars().all()
        if db_tasks:
            for t in db_tasks:
                tasks_data.append({
                    "task_id": t.task_id,
                    "title": t.title,
                    "description": t.description,
                    "target_files": t.target_files or [],
                    "acceptance_criteria": t.acceptance_criteria or [],
                    "dependencies": t.dependencies or [],
                    "pattern_refs": t.pattern_refs or [],
                    "requirement_refs": t.requirement_refs or [],
                    "order_index": t.order_index,
                    "status": "pending"
                })
        else:
            # Fallback to tasks.json on disk
            runs_dir = file_store.get_runs_dir(project_id, planning_run_id)
            tasks_file = runs_dir / "tasks.json"
            if tasks_file.exists():
                try:
                    with open(tasks_file, "r", encoding="utf-8") as f:
                        tasks_data = json.load(f).get("tasks", [])
                except Exception:
                    pass

    if not tasks_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {
                "code": "NO_TASKS_FOUND",
                "message": f"No tasks found for planning run '{planning_run_id}'.",
                "details": None
            }}
        )

    # 4. Load requirements_doc and architecture
    requirements_doc = {}
    architecture = {}
    plan_runs_dir = file_store.get_runs_dir(project_id, planning_run_id)
    arch_file = plan_runs_dir / "architecture.json"
    if arch_file.exists():
        try:
            with open(arch_file, "r", encoding="utf-8") as f:
                architecture = json.load(f)
        except Exception:
            pass

    req_run_id = (plan_run.input_data or {}).get("requirements_run_id")
    if req_run_id:
        req_runs_dir = file_store.get_runs_dir(project_id, req_run_id)
        req_file = req_runs_dir / "requirements.json"
        if req_file.exists():
            try:
                with open(req_file, "r", encoding="utf-8") as f:
                    requirements_doc = json.load(f)
            except Exception:
                pass

    # 5. Create new Run record
    run_id = str(uuid.uuid4())
    new_run = Run(
        id=run_id,
        project_id=project_id,
        workflow_name="codegen",
        status="pending",
        current_node="START",
        input_data={"planning_run_id": planning_run_id, "task_count": len(tasks_data)}
    )
    db.add(new_run)
    await db.commit()
    await db.refresh(new_run)

    # Clone tasks into the new codegen run
    for idx, t in enumerate(tasks_data):
        codegen_task = Task(
            id=str(uuid.uuid4()),
            project_id=project_id,
            run_id=run_id,
            task_id=t.get("task_id") or f"TASK-{idx+1:02d}",
            title=t.get("title") or f"Task {idx+1}",
            description=t.get("description", ""),
            target_files=t.get("target_files") or [],
            acceptance_criteria=t.get("acceptance_criteria") or [],
            dependencies=t.get("dependencies") or [],
            pattern_refs=t.get("pattern_refs") or [],
            requirement_refs=t.get("requirement_refs") or [],
            order_index=t.get("order_index", idx + 1),
            status="pending"
        )
        db.add(codegen_task)
    await db.commit()

    # 6. Start background execution
    try:
        await workflow_runner.start_codegen_run(
            project_id=project_id,
            run_id=run_id,
            tasks=tasks_data,
            requirements_doc=requirements_doc,
            architecture=architecture,
            planning_run_id=planning_run_id
        )
    except Exception as exc:
        new_run.status = "failed"
        new_run.error_message = f"Failed to start workflow: {str(exc)}"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": {
                "code": "WORKFLOW_START_FAILED",
                "message": f"Failed to start codegen workflow: {str(exc)}",
                "details": None
            }}
        )

    return Response(
        status_code=status.HTTP_202_ACCEPTED,
        content=json.dumps({
            "run_id": run_id,
            "project_id": project_id,
            "workflow": "codegen",
            "status": "pending",
            "task_count": len(tasks_data),
            "location": f"/projects/{project_id}/runs/{run_id}",
            "events_url": f"/projects/{project_id}/runs/{run_id}/events",
            "hitl_ws_url": f"/projects/{project_id}/runs/{run_id}/hitl"
        }),
        headers={
            "Location": f"/projects/{project_id}/runs/{run_id}",
            "Content-Type": "application/json"
        }
    )


# ==========================================
# 2. Get Run Details & Observability
# ==========================================
@router.get(
    "/runs/{run_id}",
    summary="Get workflow run status and telemetry"
)
async def get_run_status(
    project_id: str,
    run_id: str,
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(
        select(Run).where(Run.id == run_id, Run.project_id == project_id)
    )
    run_record = res.scalar_one_or_none()
    if not run_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Run '{run_id}' not found in project '{project_id}'", "details": None}}
        )

    # Calculate token usage totals
    u_res = await db.execute(
        select(
            func.coalesce(func.sum(Usage.tokens_in), 0),
            func.coalesce(func.sum(Usage.tokens_out), 0),
            func.coalesce(func.sum(Usage.cost_usd), 0.0)
        ).where(Usage.run_id == run_id)
    )
    tokens_in, tokens_out, cost_usd = u_res.one()

    # Check for artifacts on disk
    runs_dir = file_store.get_runs_dir(project_id, run_id)
    artifacts = []
    potential_artifacts = [
        "requirements.md", "requirements.json",
        "architecture.md", "architecture.json",
        "tasks.json", "research.json", "patterns_report.json",
        "bundle.zip", "MANIFEST.json"
    ]
    for art in potential_artifacts:
        if (runs_dir / art).exists():
            artifacts.append(art)

    return {
        "id": run_record.id,
        "project_id": run_record.project_id,
        "workflow_name": run_record.workflow_name,
        "status": run_record.status,
        "stage": run_record.current_node,
        "current_node": run_record.current_node,
        "iteration_count": (run_record.output_data or {}).get("critic_iterations", 1) if run_record.output_data else 1,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "total_tokens": tokens_in + tokens_out,
        "cost_usd": round(cost_usd, 6),
        "artifacts": artifacts,
        "error_message": run_record.error_message,
        "started_at": run_record.started_at,
        "completed_at": run_record.completed_at
    }


# ==========================================
# 3. Server-Sent Events (SSE) Progress Stream
# ==========================================
@router.get(
    "/runs/{run_id}/events",
    summary="One-way live SSE progress stream for a run"
)
async def stream_run_events(
    project_id: str,
    run_id: str,
    request: Request,
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    # Verify run exists
    res = await db.execute(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Run '{run_id}' not found in project '{project_id}'", "details": None}}
        )

    parsed_last_id = None
    if last_event_id:
        try:
            parsed_last_id = int(last_event_id)
        except Exception:
            pass

    async def _sse_generator():
        async for event in event_hub.subscribe(project_id, run_id, parsed_last_id, db):
            if await request.is_disconnected():
                break
            evt_id = event.get("id", 0)
            evt_type = event.get("event", "message")
            data_json = json.dumps(event.get("data", {}))
            yield f"id: {evt_id}\nevent: {evt_type}\ndata: {data_json}\n\n"

    return StreamingResponse(
        _sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ==========================================
# 4. REST Fallbacks for HITL Interactions
# ==========================================
@router.post(
    "/runs/{run_id}/clarifications",
    summary="REST Fallback: Submit clarification answers"
)
async def submit_clarification_rest(
    project_id: str,
    run_id: str,
    body: Dict[str, Any],
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    answers = body.get("answers", [])
    await workflow_runner.resume_run(project_id, run_id, {"answers": answers})
    return {"status": "resumed", "run_id": run_id, "answers_submitted": len(answers)}


@router.post(
    "/runs/{run_id}/approve",
    summary="REST Fallback: Approve output artifact"
)
async def approve_run_rest(
    project_id: str,
    run_id: str,
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    await workflow_runner.resume_run(project_id, run_id, {"decision": "approve"})
    return {"status": "approved", "run_id": run_id}


@router.post(
    "/runs/{run_id}/reject",
    summary="REST Fallback: Reject output artifact with feedback"
)
async def reject_run_rest(
    project_id: str,
    run_id: str,
    body: Dict[str, Any],
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    feedback = body.get("feedback", "Please revise specification.")
    await workflow_runner.resume_run(project_id, run_id, {"decision": "reject", "feedback": feedback})
    return {"status": "rejected_with_feedback", "run_id": run_id, "feedback": feedback}


@router.post(
    "/runs/{run_id}/resume",
    summary="Manually resume a paused run"
)
async def resume_run_manual(
    project_id: str,
    run_id: str,
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    await workflow_runner.resume_run(project_id, run_id, {"action": "resume"})
    return {"status": "resumed", "run_id": run_id}


# ==========================================
# 5. Artifact Downloads
# ==========================================
@router.get(
    "/runs/{run_id}/artifacts/{filename}",
    summary="Download generated run artifact file"
)
async def download_run_artifact(
    project_id: str,
    run_id: str,
    filename: str,
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    file_path = file_store.get_runs_dir(project_id, run_id) / filename
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Artifact '{filename}' not found for run '{run_id}'", "details": None}}
        )
    return FileResponse(path=str(file_path), filename=filename)


@router.get(
    "/runs/{run_id}/bundle",
    summary="Download the complete generated code bundle zip"
)
async def download_bundle(
    project_id: str,
    run_id: str,
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    bundle_path = file_store.get_runs_dir(project_id, run_id) / "bundle.zip"
    if not bundle_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "BUNDLE_NOT_FOUND", "message": f"Code bundle not yet generated for run '{run_id}'", "details": None}}
        )
    return FileResponse(path=str(bundle_path), filename=f"{project_id}_code_bundle.zip", media_type="application/zip")


@router.get(
    "/runs/{run_id}/artifacts",
    summary="Stream the final downloadable codebase bundle"
)
async def stream_run_artifacts(
    project_id: str,
    run_id: str,
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    bundle_path = file_store.get_runs_dir(project_id, run_id) / "bundle.zip"
    if not bundle_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "BUNDLE_NOT_FOUND", "message": f"Code bundle not yet generated for run '{run_id}'", "details": None}}
        )
    return FileResponse(path=str(bundle_path), filename=f"{project_id}_code_bundle.zip", media_type="application/zip")



@router.put(
    "/runs/{run_id}/artifacts/{filename}",
    summary="Update or edit generated run artifact file"
)
async def update_run_artifact(
    project_id: str,
    run_id: str,
    filename: str,
    request: Request,
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    runs_dir = file_store.get_runs_dir(project_id, run_id)
    file_path = runs_dir / filename
    body_bytes = await request.body()
    if not body_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "EMPTY_PAYLOAD", "message": "Payload cannot be empty", "details": None}}
        )

    if filename.endswith(".json"):
        try:
            parsed_json = json.loads(body_bytes.decode("utf-8"))
            file_path.write_text(json.dumps(parsed_json, indent=2), encoding="utf-8")
            res = await db.execute(select(Run).where(Run.id == run_id, Run.project_id == project_id))
            r = res.scalar_one_or_none()
            if r:
                r.output_data = {"requirements_json": parsed_json}
                await db.commit()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": {"code": "INVALID_JSON", "message": f"Invalid JSON payload: {e}", "details": None}}
            )
    else:
        file_path.write_bytes(body_bytes)

    return {"status": "updated", "filename": filename, "run_id": run_id, "size_bytes": file_path.stat().st_size}


# ==========================================
# 6. Task Management Endpoints
# ==========================================
@router.get(
    "/runs/{run_id}/tasks",
    summary="Retrieve the ordered code-ready task plan for a run"
)
async def get_run_tasks(
    project_id: str,
    run_id: str,
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    # Verify run
    res = await db.execute(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    run_record = res.scalar_one_or_none()
    if not run_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Run '{run_id}' not found", "details": None}}
        )

    # First check database tasks table
    t_res = await db.execute(
        select(Task).where(Task.run_id == run_id, Task.project_id == project_id).order_by(Task.order_index.asc())
    )
    db_tasks = t_res.scalars().all()
    if db_tasks:
        return [
            {
                "id": t.id,
                "task_id": t.task_id,
                "title": t.title,
                "description": t.description,
                "target_files": t.target_files,
                "acceptance_criteria": t.acceptance_criteria,
                "dependencies": t.dependencies,
                "pattern_refs": t.pattern_refs,
                "requirement_refs": t.requirement_refs,
                "order_index": t.order_index,
                "status": t.status
            }
            for t in db_tasks
        ]

    # Fallback to tasks.json on disk
    runs_dir = file_store.get_runs_dir(project_id, run_id)
    tasks_file = runs_dir / "tasks.json"
    if tasks_file.exists():
        try:
            with open(tasks_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("tasks", [])
        except Exception:
            pass

    return []


@router.patch(
    "/runs/{run_id}/tasks/{task_id}",
    summary="Edit, reorder, or split a task before approval"
)
async def patch_run_task(
    project_id: str,
    run_id: str,
    task_id: str,
    body: TaskPatchRequest,
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    runs_dir = file_store.get_runs_dir(project_id, run_id)
    tasks_file = runs_dir / "tasks.json"
    if not tasks_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "TASKS_NOT_FOUND", "message": f"Tasks artifact not found for run '{run_id}'", "details": None}}
        )

    with open(tasks_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    tasks = data.get("tasks", [])

    body_dict = body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else (body or {})
    action = body_dict.get("action", "edit")

    if action == "split":
        subtasks_data = body_dict.get("split_into", [])
        try:
            tasks = split_task(tasks, task_id, subtasks_data)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": {"code": "SPLIT_FAILED", "message": str(e), "details": None}}
            )
    elif action == "reorder":
        new_order_ids = body_dict.get("order", [])
        id_map = {t["task_id"]: t for t in tasks}
        if set(new_order_ids) != set(id_map.keys()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": {"code": "INVALID_ORDER", "message": "Reorder list must contain all existing task IDs", "details": None}}
            )
        reordered = [id_map[tid] for tid in new_order_ids]
        for idx, t in enumerate(reordered):
            t["order_index"] = idx + 1
        is_valid, errs, _ = validate_task_dag(reordered)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": {"code": "DAG_VIOLATION", "message": f"Reordering violates DAG: {', '.join(errs)}", "details": errs}}
            )
        tasks = reordered
    else:  # "edit"
        found = False
        for t in tasks:
            if t.get("task_id") == task_id:
                found = True
                if "title" in body_dict:
                    t["title"] = body_dict["title"]
                if "description" in body_dict:
                    t["description"] = body_dict["description"]
                if "target_files" in body_dict:
                    t["target_files"] = body_dict["target_files"]
                if "acceptance_criteria" in body_dict:
                    t["acceptance_criteria"] = body_dict["acceptance_criteria"]
                if "dependencies" in body_dict:
                    t["dependencies"] = body_dict["dependencies"]
                if "pattern_refs" in body_dict:
                    t["pattern_refs"] = body_dict["pattern_refs"]
                break
        if not found:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": {"code": "TASK_NOT_FOUND", "message": f"Task '{task_id}' not found", "details": None}}
            )
        is_valid, errs, _ = validate_task_dag(tasks)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": {"code": "DAG_VIOLATION", "message": f"Edit violates DAG: {', '.join(errs)}", "details": errs}}
            )

    # Save back to tasks.json
    with open(tasks_file, "w", encoding="utf-8") as f:
        json.dump({"tasks": tasks}, f, indent=2)

    # Also update DB tasks table
    from sqlalchemy import delete
    await db.execute(delete(Task).where(Task.run_id == run_id))
    for idx, t in enumerate(tasks):
        db_task = Task(
            id=str(uuid.uuid4()),
            project_id=project_id,
            run_id=run_id,
            task_id=t.get("task_id", f"TASK-{idx+1:02d}"),
            title=t.get("title", ""),
            description=t.get("description", ""),
            target_files=t.get("target_files", []),
            acceptance_criteria=t.get("acceptance_criteria", []),
            dependencies=t.get("dependencies", []),
            pattern_refs=t.get("pattern_refs", []),
            requirement_refs=t.get("requirement_refs", []),
            order_index=t.get("order_index", idx + 1),
            status="pending"
        )
        db.add(db_task)
    await db.commit()

    return {"status": "updated", "task_id": task_id, "tasks_count": len(tasks), "tasks": tasks}


@router.get(
    "/runs/{run_id}/research",
    summary="Retrieve the cited research log for a planning run"
)
async def get_run_research(
    project_id: str,
    run_id: str,
    db: AsyncSession = Depends(db_module.get_db),
    user: dict = Depends(get_current_user)
):
    runs_dir = file_store.get_runs_dir(project_id, run_id)
    res_file = runs_dir / "research.json"
    if not res_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "RESEARCH_NOT_FOUND", "message": f"Research log not found for run '{run_id}'", "details": None}}
        )
    with open(res_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

