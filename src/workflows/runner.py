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
from src.workflows.planning.graph import build_planning_graph
from src.workflows.codegen.graph import build_codegen_graph

logger = logging.getLogger("workflow_runner")


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
                db_path = str(settings.CHECKPOINT_DB_PATH.resolve())
                async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
                    compiled_graph = build_requirements_graph().compile(checkpointer=checkpointer)
                    
                    async for chunk in compiled_graph.astream(initial_state, config, stream_mode="values"):
                        current_node = chunk.get("current_node", "")
                        logger.info(f"[{run_id}] Requirements state advanced. Current node: {current_node}")
                        
                        async with db_module.AsyncSessionLocal() as session:
                            from sqlalchemy import select
                            r_res = await session.execute(select(Run).where(Run.id == run_id))
                            r = r_res.scalar_one_or_none()
                            if r:
                                r.current_node = current_node
                                await session.commit()

                    # Check if stream paused on an interrupt
                    graph_state = await compiled_graph.aget_state(config)
                    has_interrupt = any(bool(t.interrupts) for t in graph_state.tasks) if graph_state.tasks else False
                    if has_interrupt:
                        async with db_module.AsyncSessionLocal() as session:
                            from sqlalchemy import select
                            r_res = await session.execute(select(Run).where(Run.id == run_id))
                            r = r_res.scalar_one_or_none()
                            if r and r.status != "completed":
                                r.status = "paused"
                                await session.commit()

            except Exception as e:
                logger.exception(f"[{run_id}] Requirements execution error: {e}")
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

    async def start_planning_run(
        self,
        project_id: str,
        run_id: str,
        requirements_doc: Dict[str, Any],
        requirements_run_id: Optional[str] = None
    ) -> None:
        config = self._get_config(project_id, run_id)

        initial_state = {
            "project_id": project_id,
            "run_id": run_id,
            "requirements_run_id": requirements_run_id,
            "requirements_doc": requirements_doc,
            "complexity_path": "heavyweight",
            "selected_patterns": [],
            "research_findings": [],
            "architecture": {},
            "architecture_md": "",
            "tasks": [],
            "critic_score": 0.0,
            "critic_feedback": None,
            "critic_warnings": [],
            "critic_iterations": 0,
            "approval_status": "pending",
            "user_feedback": None,
            "reentry_node": None,
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
        async def _planning_loop():
            try:
                db_path = str(settings.CHECKPOINT_DB_PATH.resolve())
                async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
                    compiled_graph = build_planning_graph().compile(checkpointer=checkpointer)
                    
                    async for chunk in compiled_graph.astream(initial_state, config, stream_mode="values"):
                        current_node = chunk.get("current_node", "")
                        logger.info(f"[{run_id}] Planning state advanced. Current node: {current_node}")
                        
                        async with db_module.AsyncSessionLocal() as session:
                            from sqlalchemy import select
                            r_res = await session.execute(select(Run).where(Run.id == run_id))
                            r = r_res.scalar_one_or_none()
                            if r:
                                r.current_node = current_node
                                await session.commit()

                    # Check if stream paused on an interrupt
                    graph_state = await compiled_graph.aget_state(config)
                    has_interrupt = any(bool(t.interrupts) for t in graph_state.tasks) if graph_state.tasks else False
                    if has_interrupt:
                        async with db_module.AsyncSessionLocal() as session:
                            from sqlalchemy import select
                            r_res = await session.execute(select(Run).where(Run.id == run_id))
                            r = r_res.scalar_one_or_none()
                            if r and r.status != "completed":
                                r.status = "paused"
                                await session.commit()

            except Exception as e:
                logger.exception(f"[{run_id}] Planning execution error: {e}")
                async with db_module.AsyncSessionLocal() as session:
                    from sqlalchemy import select
                    r_res = await session.execute(select(Run).where(Run.id == run_id))
                    r = r_res.scalar_one_or_none()
                    if r:
                        r.status = "failed"
                        r.error_message = str(e)
                    await session.commit()
                await event_hub.publish(project_id, run_id, "error", {"error": str(e)})

        task = asyncio.create_task(_planning_loop())
        self._active_tasks[f"{project_id}_{run_id}"] = task

    async def start_codegen_run(
        self,
        project_id: str,
        run_id: str,
        tasks: list,
        requirements_doc: Dict[str, Any],
        architecture: Dict[str, Any],
        planning_run_id: Optional[str] = None
    ) -> None:
        config = self._get_config(project_id, run_id)

        initial_state = {
            "project_id": project_id,
            "run_id": run_id,
            "planning_run_id": planning_run_id,
            "requirements_doc": requirements_doc,
            "architecture": architecture,
            "tasks": tasks,
            "current_task_index": 0,
            "completed_tasks": [],
            "workspace_files": [],
            "current_task_files": [],
            "current_task_iteration": 0,
            "current_task_review": None,
            "approval_status": "pending",
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
        async def _codegen_loop():
            try:
                db_path = str(settings.CHECKPOINT_DB_PATH.resolve())
                async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
                    compiled_graph = build_codegen_graph().compile(checkpointer=checkpointer)
                    
                    async for chunk in compiled_graph.astream(initial_state, config, stream_mode="values"):
                        current_node = chunk.get("current_node", "")
                        logger.info(f"[{run_id}] Codegen state advanced. Current node: {current_node}")
                        
                        async with db_module.AsyncSessionLocal() as session:
                            from sqlalchemy import select
                            r_res = await session.execute(select(Run).where(Run.id == run_id))
                            r = r_res.scalar_one_or_none()
                            if r:
                                r.current_node = current_node
                                await session.commit()

                    # Check if stream paused on an interrupt
                    graph_state = await compiled_graph.aget_state(config)
                    has_interrupt = any(bool(t.interrupts) for t in graph_state.tasks) if graph_state.tasks else False
                    if has_interrupt:
                        async with db_module.AsyncSessionLocal() as session:
                            from sqlalchemy import select
                            r_res = await session.execute(select(Run).where(Run.id == run_id))
                            r = r_res.scalar_one_or_none()
                            if r and r.status != "completed":
                                r.status = "paused"
                                await session.commit()

            except Exception as e:
                logger.exception(f"[{run_id}] Codegen execution error: {e}")
                async with db_module.AsyncSessionLocal() as session:
                    from sqlalchemy import select
                    r_res = await session.execute(select(Run).where(Run.id == run_id))
                    r = r_res.scalar_one_or_none()
                    if r:
                        r.status = "failed"
                        r.error_message = str(e)
                    await session.commit()
                await event_hub.publish(project_id, run_id, "error", {"error": str(e)})

        task = asyncio.create_task(_codegen_loop())
        self._active_tasks[f"{project_id}_{run_id}"] = task

    async def resume_run(
        self,
        project_id: str,
        run_id: str,
        resume_value: Any
    ) -> Dict[str, Any]:
        config = self._get_config(project_id, run_id)
        db_path = str(settings.CHECKPOINT_DB_PATH.resolve())

        # Determine workflow_name from DB
        workflow_name = "requirements"
        async with db_module.AsyncSessionLocal() as session:
            from sqlalchemy import select
            r_res = await session.execute(select(Run).where(Run.id == run_id))
            r = r_res.scalar_one_or_none()
            if r and r.workflow_name:
                workflow_name = r.workflow_name

        logger.info(f"[{run_id}] Resuming {workflow_name} run with value: {resume_value}")

        # Update run record to running
        async with db_module.AsyncSessionLocal() as session:
            from sqlalchemy import select
            r_res = await session.execute(select(Run).where(Run.id == run_id))
            r = r_res.scalar_one_or_none()
            if r:
                r.status = "running"
                await session.commit()

        async def _resume_loop():
            try:
                async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
                    if workflow_name == "codegen":
                        compiled_graph = build_codegen_graph().compile(checkpointer=checkpointer)
                    elif workflow_name == "planning":
                        compiled_graph = build_planning_graph().compile(checkpointer=checkpointer)
                    else:
                        compiled_graph = build_requirements_graph().compile(checkpointer=checkpointer)

                    graph_state = await compiled_graph.aget_state(config)
                    has_interrupt = any(bool(t.interrupts) for t in graph_state.tasks) if graph_state.tasks else False
                    resume_input = Command(resume=resume_value) if has_interrupt else None

                    async for chunk in compiled_graph.astream(resume_input, config, stream_mode="values"):
                        current_node = chunk.get("current_node", "")
                        logger.info(f"[{run_id}] Resumed {workflow_name} execution. Current node: {current_node}")
                        
                        async with db_module.AsyncSessionLocal() as session:
                            from sqlalchemy import select
                            r_res = await session.execute(select(Run).where(Run.id == run_id))
                            r = r_res.scalar_one_or_none()
                            if r:
                                r.current_node = current_node
                                await session.commit()

                    # Check if resumed stream paused on another interrupt
                    graph_state = await compiled_graph.aget_state(config)
                    has_interrupt = any(bool(t.interrupts) for t in graph_state.tasks) if graph_state.tasks else False
                    if has_interrupt:
                        async with db_module.AsyncSessionLocal() as session:
                            from sqlalchemy import select
                            r_res = await session.execute(select(Run).where(Run.id == run_id))
                            r = r_res.scalar_one_or_none()
                            if r and r.status != "completed":
                                r.status = "paused"
                                await session.commit()

            except Exception as e:
                logger.exception(f"[{run_id}] Resume error: {e}")
                await event_hub.publish(project_id, run_id, "error", {"error": str(e)})

        task = asyncio.create_task(_resume_loop())
        self._active_tasks[f"{project_id}_{run_id}"] = task
        return {"status": "resumed", "run_id": run_id}


workflow_runner = WorkflowRunner()
