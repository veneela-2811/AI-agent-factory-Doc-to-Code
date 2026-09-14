import asyncio
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from langgraph.types import Command
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from config.settings import settings
import src.storage.database as db_module
from src.storage.models import Project, Run
from src.observability.events import event_hub
from src.workflows.requirements.graph import build_requirements_graph

logger = logging.getLogger("workflow_runner")

# In-memory registry of active compiled graphs
_requirements_graph = None


def get_requirements_graph():
    global _requirements_graph
    if _requirements_graph is None:
        builder = build_requirements_graph()
        _requirements_graph = builder.compile()
    return _requirements_graph


class WorkflowRunner:
    def __init__(self):
        self._active_tasks: Dict[str, asyncio.Task] = {}

    def _get_config(self, project_id: str, run_id: str) -> Dict[str, Any]:
        return {
            "configurable": {
                "thread_id": f"{project_id}_{run_id}",
                "project_id": project_id,
                "run_id": run_id
            }
        }

    async def start_requirements_run(
        self,
        project_id: str,
        run_id: str,
        document_ids: list
    ) -> None:
        graph = get_requirements_graph()
        config = self._get_config(project_id, run_id)

        initial_state = {
            "project_id": project_id,
            "run_id": run_id,
            "document_ids": document_ids,
            "document_chunks": [],
            "gap_analysis_rounds": 0,
            "has_critical_gaps": False,
            "clarification_questions": [],
            "clarification_answers": [],
            "requirements_md": "",
            "requirements_json": {},
            "approval_status": "pending",
            "user_feedback": None,
            "current_node": "START",
            "error": None
        }

        # Update run record to running
        async with db_module.AsyncSessionLocal() as session:
            from sqlalchemy import select
            r_res = await session.execute(select(Run).where(Run.id == run_id))
            r = r_res.scalar_one_or_none()
            if r:
                r.status = "running"
                r.started_at = datetime.now(timezone.utc)
            
            p_res = await session.execute(select(Project).where(Project.id == project_id))
            p = p_res.scalar_one_or_none()
            if p:
                p.status = "running"
            await session.commit()

        # Run background loop
        async def _run_loop():
            try:
                # AsyncSqliteSaver context
                db_path = str(settings.CHECKPOINT_DB_PATH.resolve())
                async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
                    compiled_graph = build_requirements_graph().compile(checkpointer=checkpointer)
                    
                    # Stream graph execution until interrupt or completion
                    async for chunk in compiled_graph.astream(initial_state, config, stream_mode="values"):
                        current_node = chunk.get("current_node", "")
                        logger.info(f"[{run_id}] State advanced. Current node: {current_node}")
                        
                        # Update run record current_node
                        async with db_module.AsyncSessionLocal() as session:
                            from sqlalchemy import select
                            r_res = await session.execute(select(Run).where(Run.id == run_id))
                            r = r_res.scalar_one_or_none()
                            if r:
                                r.current_node = current_node
                                await session.commit()

            except Exception as e:
                logger.exception(f"[{run_id}] Graph execution error: {e}")
                async with db_module.AsyncSessionLocal() as session:
                    from sqlalchemy import select
                    r_res = await session.execute(select(Run).where(Run.id == run_id))
                    r = r_res.scalar_one_or_none()
                    if r:
                        r.status = "failed"
                        r.error_message = str(e)
                    await session.commit()
                await event_hub.publish(project_id, run_id, "error", {"error": str(e)})

        task = asyncio.create_task(_run_loop())
        self._active_tasks[f"{project_id}_{run_id}"] = task

    async def resume_run(
        self,
        project_id: str,
        run_id: str,
        resume_value: Any
    ) -> Dict[str, Any]:
        config = self._get_config(project_id, run_id)
        db_path = str(settings.CHECKPOINT_DB_PATH.resolve())

        logger.info(f"[{run_id}] Resuming run with value: {resume_value}")

        async def _resume_loop():
            try:
                async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
                    compiled_graph = build_requirements_graph().compile(checkpointer=checkpointer)
                    
                    # Send Command(resume=...)
                    async for chunk in compiled_graph.astream(Command(resume=resume_value), config, stream_mode="values"):
                        current_node = chunk.get("current_node", "")
                        logger.info(f"[{run_id}] Resumed execution state. Current node: {current_node}")
                        
                        async with db_module.AsyncSessionLocal() as session:
                            from sqlalchemy import select
                            r_res = await session.execute(select(Run).where(Run.id == run_id))
                            r = r_res.scalar_one_or_none()
                            if r:
                                r.current_node = current_node
                                await session.commit()
            except Exception as e:
                logger.exception(f"[{run_id}] Resume error: {e}")
                await event_hub.publish(project_id, run_id, "error", {"error": str(e)})

        task = asyncio.create_task(_resume_loop())
        self._active_tasks[f"{project_id}_{run_id}"] = task
        return {"status": "resumed", "run_id": run_id}


workflow_runner = WorkflowRunner()
