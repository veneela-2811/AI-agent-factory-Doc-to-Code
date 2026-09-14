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

from config.settings import settings
import src.storage.database as db_module
from src.storage.models import Project, Run, Usage, RunEvent
from src.storage.filestore import file_store
from src.auth.dependencies import get_current_user
from src.observability.events import event_hub
from src.workflows.runner import workflow_runner
from src.api.schemas import ErrorEnvelope

logger = logging.getLogger("workflow_routes")
router = APIRouter(prefix="/projects/{project_id}", tags=["Workflows & Runs"])


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
    body: Optional[Dict[str, Any]] = None,
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

    document_ids = (body or {}).get("document_ids", [])
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
    if (runs_dir / "requirements.md").exists():
        artifacts.append("requirements.md")
    if (runs_dir / "requirements.json").exists():
        artifacts.append("requirements.json")

    return {
        "id": run_record.id,
        "project_id": run_record.project_id,
        "workflow_name": run_record.workflow_name,
        "status": run_record.status,
        "current_node": run_record.current_node,
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

