import os
import json
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from config.settings import settings
import src.storage.database as db_module
from src.storage.models import Project, Run, Usage, Task
from src.storage.filestore import file_store
from src.observability.events import event_hub
from src.workflows.codegen.state import CodegenGraphState
from src.workflows.codegen.task_subgraphs import execute_task_subgraph
from src.workflows.codegen.reviewers import run_parallel_reviewers
from src.workflows.codegen.manifest_generator import generate_manifest_and_bundle

logger = logging.getLogger("codegen_workflow")


# ==========================================
# 1. Initialize Workspace Node
# ==========================================
async def init_workspace_node(state: CodegenGraphState) -> Dict[str, Any]:
    project_id = state["project_id"]
    run_id = state["run_id"]
    tasks = state.get("tasks", [])

    logger.info(f"[{run_id}] Initializing codegen workspace for {len(tasks)} tasks.")
    await event_hub.publish(project_id, run_id, "node_started", {"node": "init_workspace", "task_count": len(tasks)})

    workspace_dir = file_store.get_workspace_dir(project_id, run_id)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Check for already completed tasks in DB (resume support)
    completed_task_ids = set()
    async with db_module.AsyncSessionLocal() as session:
        from sqlalchemy import select
        res = await session.execute(
            select(Task).where(Task.run_id == run_id, Task.status == "completed")
        )
        for t in res.scalars().all():
            completed_task_ids.add(t.task_id)

    # Determine starting index
    start_index = 0
    for idx, t in enumerate(tasks):
        if t.get("task_id") in completed_task_ids:
            start_index = idx + 1
        else:
            break

    logger.info(f"[{run_id}] Resuming codegen from task index {start_index} (Completed: {len(completed_task_ids)})")
    await event_hub.publish(project_id, run_id, "node_completed", {
        "node": "init_workspace",
        "start_index": start_index
    })

    return {
        "current_task_index": start_index,
        "completed_tasks": list(state.get("completed_tasks", [])),
        "current_node": "init_workspace"
    }


# ==========================================
# 2. Dispatch Task Node (Orchestrator-Worker)
# ==========================================
async def dispatch_task_node(state: CodegenGraphState) -> Dict[str, Any]:
    project_id = state["project_id"]
    run_id = state["run_id"]
    tasks = state.get("tasks", [])
    current_idx = state.get("current_task_index", 0)
    completed_tasks = list(state.get("completed_tasks", []))
    iteration = state.get("current_task_iteration", 0)
    prev_review = state.get("current_task_review") or {}
    feedback = prev_review.get("feedback") if iteration > 0 else None

    if current_idx >= len(tasks):
        return {"current_node": "dispatch_task"}

    current_task = tasks[current_idx]
    task_id = current_task.get("task_id", f"TASK-{current_idx+1:02d}")
    title = current_task.get("title", "")

    logger.info(f"[{run_id}] Dispatching {task_id}: '{title}' (Iteration {iteration + 1})")
    await event_hub.publish(project_id, run_id, "task_started", {
        "task_id": task_id,
        "title": title,
        "iteration": iteration + 1
    })

    # Update Task status to in_progress in DB
    async with db_module.AsyncSessionLocal() as session:
        from sqlalchemy import select
        res = await session.execute(
            select(Task).where(Task.task_id == task_id, Task.run_id == run_id)
        )
        db_task = res.scalar_one_or_none()
        if db_task:
            db_task.status = "in_progress"
            await session.commit()

    # 1. Execute task-specific dynamic subgraph (Reflection, Tool-Use, or Standard)
    gen_result = await execute_task_subgraph(
        project_id=project_id,
        run_id=run_id,
        task=current_task,
        all_tasks=tasks,
        requirements_doc=state.get("requirements_doc", {}),
        architecture=state.get("architecture", {}),
        reviewer_feedback=feedback
    )

    # 2. Run Parallel Reviewers
    formatted_code = "\n\n".join([
        f"### Path: {f.path}\n```python\n{f.content}\n```"
        for f in gen_result.files
    ])

    review = await run_parallel_reviewers(
        task=current_task,
        generated_code=formatted_code,
        project_id=project_id,
        run_id=run_id
    )

    workspace_dir = file_store.get_workspace_dir(project_id, run_id)

    # Check Review Verdict
    if review.verdict == "pass":
        # Write files to workspace
        written_files = []
        for f in gen_result.files:
            file_path = workspace_dir / f.path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(f.content, encoding="utf-8")
            written_files.append(f.path)

        # Mark Task completed in DB
        async with db_module.AsyncSessionLocal() as session:
            from sqlalchemy import select
            res = await session.execute(
                select(Task).where(Task.task_id == task_id, Task.run_id == run_id)
            )
            db_t = res.scalar_one_or_none()
            if db_t:
                db_t.status = "completed"
                await session.commit()

        task_record = {
            "task_id": task_id,
            "title": title,
            "status": "completed",
            "target_files": written_files,
            "pattern_refs": current_task.get("pattern_refs", []),
            "iterations": iteration + 1,
            "review": review.model_dump()
        }
        completed_tasks.append(task_record)

        await event_hub.publish(project_id, run_id, "task_completed", {
            "task_id": task_id,
            "files_written": written_files,
            "review": review.model_dump()
        })

        return {
            "current_task_index": current_idx + 1,
            "current_task_iteration": 0,
            "current_task_review": None,
            "completed_tasks": completed_tasks,
            "current_node": "dispatch_task"
        }

    else:
        # Review failed
        if iteration < 1:  # Capped at 2 iterations (0, 1)
            logger.info(f"[{run_id}][{task_id}] Review failed. Iterating with feedback.")
            return {
                "current_task_iteration": iteration + 1,
                "current_task_review": review.model_dump(),
                "completed_tasks": completed_tasks,
                "current_node": "dispatch_task"
            }
        else:
            # Exhausted retries -> Pause for HITL Escalation Request
            logger.warning(f"[{run_id}][{task_id}] Retries exhausted. Triggering HITL Escalation Interrupt.")
            escalation_payload = {
                "type": "escalation_request",
                "task_id": task_id,
                "title": title,
                "defects": review.feedback,
                "failed_reviewers": review.failed_reviewers,
                "has_security_veto": review.has_security_veto,
                "files": [f.model_dump() for f in gen_result.files]
            }

            await event_hub.publish(project_id, run_id, "escalation_requested", escalation_payload)

            # LangGraph Interrupt: Pauses execution until client responds
            user_response = interrupt(escalation_payload)

            decision = "approve"
            if isinstance(user_response, dict):
                decision = user_response.get("decision", "approve")

            logger.info(f"[{run_id}][{task_id}] Resumed from HITL escalation with decision: '{decision}'")

            # Write files to workspace regardless of escalation override
            written_files = []
            for f in gen_result.files:
                file_path = workspace_dir / f.path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(f.content, encoding="utf-8")
                written_files.append(f.path)

            task_status = "completed" if decision in ["approve", "override"] else "failed"
            async with db_module.AsyncSessionLocal() as session:
                from sqlalchemy import select
                res = await session.execute(
                    select(Task).where(Task.task_id == task_id, Task.run_id == run_id)
                )
                db_t = res.scalar_one_or_none()
                if db_t:
                    db_t.status = task_status
                    await session.commit()

            task_record = {
                "task_id": task_id,
                "title": title,
                "status": task_status,
                "target_files": written_files,
                "pattern_refs": current_task.get("pattern_refs", []),
                "iterations": iteration + 1,
                "review": review.model_dump()
            }
            completed_tasks.append(task_record)

            return {
                "current_task_index": current_idx + 1,
                "current_task_iteration": 0,
                "current_task_review": None,
                "completed_tasks": completed_tasks,
                "current_node": "dispatch_task"
            }


# ==========================================
# 3. Bundle and Manifest Node
# ==========================================
async def bundle_and_manifest_node(state: CodegenGraphState) -> Dict[str, Any]:
    project_id = state["project_id"]
    run_id = state["run_id"]
    completed_tasks = state.get("completed_tasks", [])

    logger.info(f"[{run_id}] Building MANIFEST.json and bundle.zip for {len(completed_tasks)} tasks.")
    await event_hub.publish(project_id, run_id, "node_started", {"node": "bundle_and_manifest"})

    bundle_info = generate_manifest_and_bundle(project_id, run_id, completed_tasks)

    await event_hub.publish(project_id, run_id, "node_completed", {
        "node": "bundle_and_manifest",
        "total_files": bundle_info["total_files"],
        "bundle_size": bundle_info["bundle_size_bytes"]
    })

    return {
        "manifest": bundle_info["manifest"],
        "bundle_path": bundle_info["bundle_path"],
        "current_node": "bundle_and_manifest"
    }


# ==========================================
# 4. Approval Gate Node (HITL Gate)
# ==========================================
async def approval_gate_node(state: CodegenGraphState) -> Dict[str, Any]:
    project_id = state["project_id"]
    run_id = state["run_id"]
    completed_tasks = state.get("completed_tasks", [])
    manifest = state.get("manifest", {})
    total_files = manifest.get("total_files", 0)

    logger.info(f"[{run_id}] Pausing at Codegen Final Approval Gate")

    req_id = str(uuid.uuid4())
    approval_payload = {
        "type": "approval_request",
        "request_id": req_id,
        "artifact": {
            "bundle_url": f"/projects/{project_id}/runs/{run_id}/artifacts/bundle.zip",
            "manifest_url": f"/projects/{project_id}/runs/{run_id}/artifacts/MANIFEST.json",
            "task_count": len(completed_tasks),
            "total_files": total_files,
            "summary": f"Completed code generation for {len(completed_tasks)} tasks across {total_files} files."
        }
    }

    await event_hub.publish(project_id, run_id, "approval_requested", approval_payload)

    # LangGraph Interrupt: Pauses execution until client sends Command(resume=...)
    user_decision = interrupt(approval_payload)

    decision = "approve"
    if isinstance(user_decision, dict):
        decision = user_decision.get("decision", "approve")

    logger.info(f"[{run_id}] Resumed from Codegen Approval Gate with decision: '{decision}'")

    return {
        "approval_status": decision,
        "current_node": "approval_gate"
    }


# ==========================================
# 5. Complete Node
# ==========================================
async def complete_node(state: CodegenGraphState) -> Dict[str, Any]:
    project_id = state["project_id"]
    run_id = state["run_id"]
    manifest = state.get("manifest", {})

    logger.info(f"[{run_id}] Finalizing codegen workflow. Marking project and run completed.")

    async with db_module.AsyncSessionLocal() as session:
        from sqlalchemy import select
        # Mark run completed
        r_res = await session.execute(select(Run).where(Run.id == run_id))
        r = r_res.scalar_one_or_none()
        if r:
            r.status = "completed"
            r.completed_at = datetime.now(timezone.utc)
            r.output_data = {
                "manifest": manifest,
                "bundle_url": f"/projects/{project_id}/runs/{run_id}/artifacts/bundle.zip"
            }

        # Mark project completed
        p_res = await session.execute(select(Project).where(Project.id == project_id))
        p = p_res.scalar_one_or_none()
        if p:
            p.status = "completed"

        await session.commit()

    await event_hub.publish(project_id, run_id, "run_completed", {
        "status": "completed",
        "decision": "approved",
        "artifacts": ["bundle.zip", "MANIFEST.json"]
    })

    return {
        "approval_status": "approved",
        "current_node": "complete"
    }


# ==========================================
# Graph Builder & Routing Conditions
# ==========================================
def orchestrator_router(state: CodegenGraphState) -> str:
    tasks = state.get("tasks", [])
    current_idx = state.get("current_task_index", 0)

    if current_idx < len(tasks):
        return "dispatch_task"
    return "bundle_and_manifest"


def build_codegen_graph() -> StateGraph:
    builder = StateGraph(CodegenGraphState)

    builder.add_node("init_workspace", init_workspace_node)
    builder.add_node("dispatch_task", dispatch_task_node)
    builder.add_node("bundle_and_manifest", bundle_and_manifest_node)
    builder.add_node("approval_gate", approval_gate_node)
    builder.add_node("complete", complete_node)

    builder.add_edge(START, "init_workspace")
    builder.add_conditional_edges(
        "init_workspace",
        orchestrator_router,
        {
            "dispatch_task": "dispatch_task",
            "bundle_and_manifest": "bundle_and_manifest"
        }
    )

    builder.add_conditional_edges(
        "dispatch_task",
        orchestrator_router,
        {
            "dispatch_task": "dispatch_task",
            "bundle_and_manifest": "bundle_and_manifest"
        }
    )

    builder.add_edge("bundle_and_manifest", "approval_gate")
    builder.add_edge("approval_gate", "complete")
    builder.add_edge("complete", END)

    return builder
