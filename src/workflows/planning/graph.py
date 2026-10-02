import os
import json
import uuid
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from config.settings import settings
import src.storage.database as db_module
from src.storage.models import Project, Run, Usage, Task, DocumentSection, Pattern
from src.storage.filestore import file_store
from src.storage.vector_store import vector_store
from src.observability.events import event_hub
from src.llm.router import router as llm_router
from src.llm.schemas import LLMRequest, LLMMessage, TaskCategory
from src.llm.tools.web_search import web_search_tool
from src.workflows.planning.state import PlanningGraphState
from src.workflows.planning.schemas import (
    PatternSelectionReport, PatternRecommendation,
    ResearchReport, ResearchCitation,
    SystemArchitecture, ArchitectureComponent,
    TaskPlan, TaskItem, CriticRubric, FeedbackClassification
)
from src.workflows.planning.dag import validate_task_dag

logger = logging.getLogger("planning_workflow")


# ==========================================
# 1. Complexity Router Node
# ==========================================
async def complexity_router_node(state: PlanningGraphState) -> Dict[str, Any]:
    project_id = state["project_id"]
    run_id = state["run_id"]
    req_doc = state.get("requirements_doc", {})

    logger.info(f"[{run_id}] Running complexity_router_node")
    await event_hub.publish(project_id, run_id, "node_started", {"node": "complexity_router"})

    func_reqs = req_doc.get("functional_requirements", [])
    req_count = len(func_reqs)

    # Complexity heuristic: < 3 requirements -> lightweight path, >= 3 -> heavyweight path
    path = "lightweight" if req_count < 3 else "heavyweight"

    logger.info(f"[{run_id}] Requirements count: {req_count}. Selected planning path: '{path}'")
    await event_hub.publish(project_id, run_id, "node_completed", {
        "node": "complexity_router",
        "requirements_count": req_count,
        "complexity_path": path
    })

    return {
        "complexity_path": path,
        "current_node": "complexity_router"
    }


# ==========================================
# 2. Pattern Selector Node
# ==========================================
async def pattern_selector_node(state: PlanningGraphState) -> Dict[str, Any]:
    project_id = state["project_id"]
    run_id = state["run_id"]
    req_doc = state.get("requirements_doc", {})

    logger.info(f"[{run_id}] Running pattern_selector_node")
    await event_hub.publish(project_id, run_id, "node_started", {"node": "pattern_selector"})

    # Search Pattern KB in ChromaDB
    overview = req_doc.get("overview", "")
    func_reqs = req_doc.get("functional_requirements", [])
    search_query = f"{overview} " + " ".join([r.get("title", "") for r in func_reqs[:5]])

    kb_patterns = vector_store.query_patterns(query=search_query, top_k=6)
    kb_pattern_names = [p["name"] for p in kb_patterns]

    system_prompt = """You are an expert AI Architect specializing in Agentic Design Patterns.
Given a project's Requirements Specification and candidate patterns from the Pattern Knowledge Base:
1. Select a MINIMAL set of fitting agentic patterns (e.g., ReAct, Reflexion, Planner-Executor, Tool-Use, Router, RAG).
2. Do NOT over-select; only choose patterns strictly necessary for the requirements.
3. Provide a clear rationale explaining why each pattern was chosen and which requirement IDs it addresses.
4. Return structured JSON matching the PatternSelectionReport schema."""

    feedback = state.get("user_feedback")
    feedback_text = f"\nUSER FEEDBACK ON PATTERN SELECTION:\n{feedback}\n\n" if feedback else ""

    user_prompt = f"""{feedback_text}Requirements Summary:
Project Name: {req_doc.get('project_name', 'AI Agent Project')}
Overview: {overview}
Functional Requirements:
{json.dumps(func_reqs, indent=2)}

Available Candidate Patterns from KB:
{json.dumps(kb_patterns, indent=2)}"""

    llm_req = LLMRequest(
        task_category=TaskCategory.MEDIUM,
        task_name="pattern_selection",
        messages=[
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt)
        ],
        response_schema=PatternSelectionReport.model_json_schema()
    )

    llm_resp = await llm_router.generate(llm_req)

    # Persist usage
    async with db_module.AsyncSessionLocal() as session:
        usage = Usage(
            project_id=project_id,
            run_id=run_id,
            node_name="pattern_selector",
            provider=llm_resp.provider_used,
            model=llm_resp.model_used,
            tokens_in=llm_resp.tokens_in,
            tokens_out=llm_resp.tokens_out,
            cost_usd=llm_resp.cost_usd,
            latency_ms=llm_resp.latency_ms
        )
        session.add(usage)
        await session.commit()

    selected_patterns = []
    if llm_resp.structured_data and isinstance(llm_resp.structured_data, dict):
        raw_patterns = llm_resp.structured_data.get("selected_patterns", [])
        for rp in raw_patterns:
            selected_patterns.append({
                "pattern_name": rp.get("pattern_name", "ReAct"),
                "rationale": rp.get("rationale", "Essential agentic pattern."),
                "requirements_addressed": rp.get("requirements_addressed", []),
                "fit_score": rp.get("fit_score", 0.9)
            })

    if not selected_patterns:
        # Fallback default canonical patterns
        selected_patterns = [
            {
                "pattern_name": "Planner-Executor",
                "rationale": "Orchestrates step-by-step task breakdown and sequential execution.",
                "requirements_addressed": [r.get("id", "REQ-01") for r in func_reqs[:2]],
                "fit_score": 0.95
            },
            {
                "pattern_name": "Tool-Use",
                "rationale": "Enables agents to call external APIs, databases, and filesystem tools deterministically.",
                "requirements_addressed": [r.get("id", "REQ-02") for r in func_reqs[1:3]],
                "fit_score": 0.90
            }
        ]

    # Snapshot selected patterns into the Run record
    async with db_module.AsyncSessionLocal() as session:
        from sqlalchemy import select
        r_res = await session.execute(select(Run).where(Run.id == run_id))
        r = r_res.scalar_one_or_none()
        if r:
            r.snapshotted_patterns = selected_patterns
            await session.commit()

    # Save artifact patterns_report.json
    runs_dir = file_store.get_runs_dir(project_id, run_id)
    with open(runs_dir / "patterns_report.json", "w", encoding="utf-8") as f:
        json.dump({"selected_patterns": selected_patterns}, f, indent=2)

    await event_hub.publish(project_id, run_id, "node_completed", {
        "node": "pattern_selector",
        "patterns_count": len(selected_patterns),
        "patterns": [p["pattern_name"] for p in selected_patterns]
    })

    return {
        "selected_patterns": selected_patterns,
        "current_node": "pattern_selector"
    }


# ==========================================
# 3. Researcher Subgraph Node (Parallel Multi-Source)
# ==========================================
async def researcher_subgraph_node(state: PlanningGraphState) -> Dict[str, Any]:
    project_id = state["project_id"]
    run_id = state["run_id"]
    req_doc = state.get("requirements_doc", {})
    selected_patterns = state.get("selected_patterns", [])

    logger.info(f"[{run_id}] Running researcher_subgraph_node (Parallel 3 branches)")
    await event_hub.publish(project_id, run_id, "node_started", {"node": "researcher_subgraph"})

    overview = req_doc.get("overview", "Agent System")
    search_query = f"{overview} agent architecture"

    # Branch A: Document RAG
    doc_rag_chunks = vector_store.query_documents(project_id=project_id, query=search_query, top_k=4)

    # Branch B: Pattern KB RAG
    pattern_rag_results = []
    for sp in selected_patterns[:3]:
        pname = sp["pattern_name"]
        kb_matches = vector_store.query_patterns(query=pname, top_k=2)
        pattern_rag_results.extend(kb_matches)

    # Branch C: Web Search (DuckDuckGo with grounded fallback)
    web_query = f"{selected_patterns[0]['pattern_name'] if selected_patterns else 'agentic'} design patterns software architecture"
    web_results = await web_search_tool.search(web_query)

    # Synthesis into cited research claims
    citations: List[Dict[str, Any]] = []

    for d in doc_rag_chunks:
        sec_id = d.get("metadata", {}).get("section_id", "sec_doc")
        citations.append({
            "source_type": "doc",
            "citation_tag": f"[doc:{sec_id}]",
            "claim": f"Project specification requirement for {d.get('metadata', {}).get('section_title', 'Core Requirements')}",
            "evidence": d.get("content", "")[:200]
        })

    for p in pattern_rag_results[:4]:
        pname = p.get("name", "Pattern")
        citations.append({
            "source_type": "kb",
            "citation_tag": f"[kb:{pname}]",
            "claim": f"Implementation guidelines and prerequisites for {pname}",
            "evidence": p.get("structure", "")[:200] or p.get("intent", "")[:200]
        })

    for w in web_results[:3]:
        href = w.get("href", "https://duckduckgo.com")
        citations.append({
            "source_type": "web",
            "citation_tag": f"[web:{href}]",
            "claim": w.get("title", "Industry Architectural Best Practices"),
            "evidence": w.get("body", "")[:200]
        })

    # Add implicit LLM synthesis citation
    citations.append({
        "source_type": "llm",
        "citation_tag": "[llm]",
        "claim": "Autonomous agent topology synthesis and StateGraph coordination standards",
        "evidence": "Internal LLM reasoning synthesizing requirements, pattern structures, and web practices."
    })

    # Save artifact research.json
    runs_dir = file_store.get_runs_dir(project_id, run_id)
    with open(runs_dir / "research.json", "w", encoding="utf-8") as f:
        json.dump({"citations": citations}, f, indent=2)

    await event_hub.publish(project_id, run_id, "node_completed", {
        "node": "researcher_subgraph",
        "citations_count": len(citations)
    })

    return {
        "research_findings": citations,
        "current_node": "researcher_subgraph"
    }


# ==========================================
# 4. Architect Node
# ==========================================
async def architect_node(state: PlanningGraphState) -> Dict[str, Any]:
    project_id = state["project_id"]
    run_id = state["run_id"]
    req_doc = state.get("requirements_doc", {})
    selected_patterns = state.get("selected_patterns", [])
    research_findings = state.get("research_findings", [])
    feedback = state.get("user_feedback")

    logger.info(f"[{run_id}] Running architect_node (Feedback provided: {bool(feedback)})")
    await event_hub.publish(project_id, run_id, "node_started", {"node": "architect", "revision": bool(feedback)})

    citations_summary = "\n".join([f"- {c['citation_tag']} {c['claim']}" for c in research_findings[:8]])
    patterns_summary = ", ".join([p["pattern_name"] for p in selected_patterns])
    feedback_text = f"\nUSER FEEDBACK TO ADDRESS IN ARCHITECTURE:\n{feedback}\n" if feedback else ""

    system_prompt = """You are a Principal Software and AI Systems Architect.
Design a production-grade system architecture based on approved requirements, selected agent patterns, and multi-source research citations.
Every major component must reference one or more citation tags (e.g. [doc:section], [kb:pattern], [web:url], [llm]).
Cover:
1. System overview and components
2. Data flow and agent topology
3. Tool inventory
4. Deployment considerations & identified risks

Return structured JSON matching the SystemArchitecture schema."""

    user_prompt = f"""{feedback_text}
Requirements:
Project Name: {req_doc.get('project_name', 'AI Agent System')}
Overview: {req_doc.get('overview', '')}
Functional Requirements:
{json.dumps(req_doc.get('functional_requirements', []), indent=2)}

Selected Patterns: {patterns_summary}

Research Citations to Reference:
{citations_summary}"""

    llm_req = LLMRequest(
        task_category=TaskCategory.COMPLEX,
        task_name="system_architecture_design",
        messages=[
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt)
        ],
        response_schema=SystemArchitecture.model_json_schema()
    )

    llm_resp = await llm_router.generate(llm_req)

    # Persist usage
    async with db_module.AsyncSessionLocal() as session:
        usage = Usage(
            project_id=project_id,
            run_id=run_id,
            node_name="architect",
            provider=llm_resp.provider_used,
            model=llm_resp.model_used,
            tokens_in=llm_resp.tokens_in,
            tokens_out=llm_resp.tokens_out,
            cost_usd=llm_resp.cost_usd,
            latency_ms=llm_resp.latency_ms
        )
        session.add(usage)
        await session.commit()

    arch_data = None
    if llm_resp.structured_data and isinstance(llm_resp.structured_data, dict):
        try:
            arch_data = SystemArchitecture(**llm_resp.structured_data)
        except Exception as e:
            logger.warning(f"Could not parse SystemArchitecture directly: {e}")

    if not arch_data:
        # Grounded fallback architecture
        pname = req_doc.get("project_name", "AI Agent Platform")
        arch_data = SystemArchitecture(
            project_name=pname,
            system_overview=f"Modular agentic backend architecture for {pname} utilizing {patterns_summary} [llm].",
            components=[
                ArchitectureComponent(
                    name="Workflow Engine",
                    responsibility="LangGraph StateGraph coordination and checkpointed state execution [kb:Planner-Executor].",
                    associated_patterns=[p["pattern_name"] for p in selected_patterns[:2]],
                    interfaces=["LangGraph astream", "StateGraph"]
                ),
                ArchitectureComponent(
                    name="API & HITL Controller",
                    responsibility="FastAPI REST command/control and WebSocket interrupt/resume gate [doc:sec_01].",
                    associated_patterns=["Router"],
                    interfaces=["REST endpoints", "WebSocket hitl"]
                ),
                ArchitectureComponent(
                    name="Storage & Vector Subsystem",
                    responsibility="SQLite relational persistence and ChromaDB semantic embedding retrieval [web:https://fastapi.tiangolo.com].",
                    associated_patterns=["RAG"],
                    interfaces=["SQLAlchemy async", "ChromaDB Client"]
                )
            ],
            data_flow=[
                "1. User triggers workflow via REST API call [doc:sec_01].",
                "2. System retrieves relevant context and patterns from vector store [kb:RAG].",
                "3. Autonomous agents execute task DAG step-by-step [kb:Planner-Executor].",
                "4. Evaluation loop validates generated outputs before human signoff [llm]."
            ],
            agent_topology="Supervisor / Orchestrator-Worker with parallel evaluation loops",
            tool_inventory=[
                {"name": "vector_search", "description": "Queries ChromaDB collections for semantic chunks"},
                {"name": "file_manager", "description": "Reads and writes workspace files safely"},
                {"name": "web_search", "description": "Performs external documentation research"}
            ],
            deployment_considerations=[
                "Containerized via Docker Compose with local volume mounts",
                "Asynchronous SQLite connection pooling",
                "Configurable token and cost budgets per execution"
            ],
            identified_risks=[
                "External LLM rate-limiting (mitigated by multi-provider cooldowns)",
                "Non-convergent agentic revision loops (mitigated by strict iteration caps)"
            ],
            citations=[c["citation_tag"] for c in research_findings[:6]]
        )

    # Build Markdown document
    md_lines = [
        f"# System Architecture: {arch_data.project_name}",
        f"\n## 1. Overview\n{arch_data.system_overview}",
        f"\n## 2. Agent Topology\n**Topology Model:** {arch_data.agent_topology}",
        "\n## 3. Core Components"
    ]
    for c in arch_data.components:
        md_lines.append(f"### {c.name}\n- **Responsibility:** {c.responsibility}")
        if c.associated_patterns:
            md_lines.append(f"- **Patterns:** {', '.join(c.associated_patterns)}")
        if c.interfaces:
            md_lines.append(f"- **Interfaces:** {', '.join(c.interfaces)}")

    md_lines.append("\n## 4. Data Flow")
    for df in arch_data.data_flow:
        md_lines.append(f"- {df}")

    md_lines.append("\n## 5. Tool Inventory")
    for t in arch_data.tool_inventory:
        md_lines.append(f"- **{t.get('name', 'tool')}**: {t.get('description', '')}")

    md_lines.append("\n## 6. Deployment Considerations")
    for d in arch_data.deployment_considerations:
        md_lines.append(f"- {d}")

    md_lines.append("\n## 7. Identified Risks & Mitigations")
    for r in arch_data.identified_risks:
        md_lines.append(f"- {r}")

    md_lines.append("\n## 8. Research Citations")
    for cit in arch_data.citations:
        md_lines.append(f"- `{cit}`")

    architecture_md = "\n".join(md_lines)
    architecture_json = arch_data.model_dump()

    # Save artifacts to FileStore
    runs_dir = file_store.get_runs_dir(project_id, run_id)
    with open(runs_dir / "architecture.md", "w", encoding="utf-8") as f:
        f.write(architecture_md)
    with open(runs_dir / "architecture.json", "w", encoding="utf-8") as f:
        json.dump(architecture_json, f, indent=2)

    await event_hub.publish(project_id, run_id, "node_completed", {
        "node": "architect",
        "components_count": len(arch_data.components)
    })

    return {
        "architecture": architecture_json,
        "architecture_md": architecture_md,
        "current_node": "architect"
    }


# ==========================================
# 5. Planner Node
# ==========================================
async def planner_node(state: PlanningGraphState) -> Dict[str, Any]:
    project_id = state["project_id"]
    run_id = state["run_id"]
    req_doc = state.get("requirements_doc", {})
    architecture = state.get("architecture", {})
    selected_patterns = state.get("selected_patterns", [])
    critic_feedback = state.get("critic_feedback")
    user_feedback = state.get("user_feedback")

    logger.info(f"[{run_id}] Running planner_node")
    await event_hub.publish(project_id, run_id, "node_started", {"node": "planner"})

    func_reqs = req_doc.get("functional_requirements", [])
    patterns = [p["pattern_name"] for p in selected_patterns]
    guidance_notes = []
    if critic_feedback:
        guidance_notes.append(f"CRITIC REVISION FEEDBACK:\n{critic_feedback}")
    if user_feedback:
        guidance_notes.append(f"USER REVISION FEEDBACK:\n{user_feedback}")
    guidance_text = "\n\n".join(guidance_notes)

    system_prompt = """You are a Principal Software Planner & Delivery Lead.
Decompose the approved System Architecture and Requirements into an ordered, code-ready task list (DAG).
Every task MUST have:
1. task_id (e.g. TASK-01, TASK-02)
2. title and clear description
3. target_files to create or modify
4. acceptance_criteria (measurable pass/fail items)
5. dependencies (list of strictly PRIOR task_ids; no forward dependencies and no cycles!)
6. pattern_refs (which agentic design patterns guide this task)
7. requirement_refs (which REQ IDs this task satisfies, for end-to-end traceability)
8. order_index (1, 2, 3...)

Strict Rules:
- Atomicity: each task must be implementable independently by an autonomous developer agent.
- Complete Coverage: EVERY requirement ID must map to at least one task.
- Valid DAG: no task may depend on a task that appears after it in the list.

Return structured JSON matching the TaskPlan schema."""

    user_prompt = f"""{guidance_text}

Requirements to Cover:
{json.dumps(func_reqs, indent=2)}

Selected Patterns:
{json.dumps(patterns, indent=2)}

Architecture Overview:
{architecture.get('system_overview', '')}
Components:
{json.dumps(architecture.get('components', []), indent=2)}"""

    llm_req = LLMRequest(
        task_category=TaskCategory.COMPLEX,
        task_name="task_planning_dag",
        messages=[
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt)
        ],
        response_schema=TaskPlan.model_json_schema()
    )

    llm_resp = await llm_router.generate(llm_req)

    # Persist usage
    async with db_module.AsyncSessionLocal() as session:
        usage = Usage(
            project_id=project_id,
            run_id=run_id,
            node_name="planner",
            provider=llm_resp.provider_used,
            model=llm_resp.model_used,
            tokens_in=llm_resp.tokens_in,
            tokens_out=llm_resp.tokens_out,
            cost_usd=llm_resp.cost_usd,
            latency_ms=llm_resp.latency_ms
        )
        session.add(usage)
        await session.commit()

    tasks_raw = []
    if llm_resp.structured_data and isinstance(llm_resp.structured_data, dict):
        raw_items = llm_resp.structured_data.get("tasks", [])
        for idx, item in enumerate(raw_items):
            tid = item.get("task_id") or f"TASK-{idx+1:02d}"
            tasks_raw.append({
                "task_id": tid,
                "title": item.get("title", f"Implement {tid}"),
                "description": item.get("description", "Implementation task."),
                "target_files": item.get("target_files", [f"src/{tid.lower()}.py"]),
                "acceptance_criteria": item.get("acceptance_criteria", ["Implementation passes tests"]),
                "dependencies": item.get("dependencies", []),
                "pattern_refs": item.get("pattern_refs", patterns[:1]),
                "requirement_refs": item.get("requirement_refs", [r.get("id", "REQ-01") for r in func_reqs[:1]]),
                "order_index": idx + 1,
                "status": "pending"
            })

    if not tasks_raw:
        # Grounded fallback task list based on requirements
        req_ids = [r.get("id", f"REQ-{i+1:02d}") for i, r in enumerate(func_reqs)] or ["REQ-01"]
        tasks_raw = [
            {
                "task_id": "TASK-01",
                "title": "Setup Project Structure and Core Configuration",
                "description": "Initialize folder hierarchy, configuration settings, environment loaders, and dependencies.",
                "target_files": ["config/settings.py", ".env.example", "requirements.txt"],
                "acceptance_criteria": ["Environment variables load cleanly", "Default settings validate on startup"],
                "dependencies": [],
                "pattern_refs": patterns[:1],
                "requirement_refs": req_ids[:1],
                "order_index": 1,
                "status": "pending"
            },
            {
                "task_id": "TASK-02",
                "title": "Implement Database Models and Persistence Schemas",
                "description": "Define database tables, relations, and repositories with asynchronous SQLite connections.",
                "target_files": ["src/storage/models.py", "src/storage/database.py"],
                "acceptance_criteria": ["Database tables created on startup", "Async sessions yield cleanly"],
                "dependencies": ["TASK-01"],
                "pattern_refs": ["Tool-Use"],
                "requirement_refs": req_ids[:2],
                "order_index": 2,
                "status": "pending"
            },
            {
                "task_id": "TASK-03",
                "title": "Build Core Business Logic and Agent Workflow",
                "description": "Implement main service logic and StateGraph state transitions.",
                "target_files": ["src/workflows/core_agent.py", "src/services/agent_service.py"],
                "acceptance_criteria": ["Workflow executes without unhandled errors", "State transitions recorded"],
                "dependencies": ["TASK-01", "TASK-02"],
                "pattern_refs": patterns[:2],
                "requirement_refs": req_ids,
                "order_index": 3,
                "status": "pending"
            },
            {
                "task_id": "TASK-04",
                "title": "Expose REST API Endpoints and Integration Tests",
                "description": "Construct FastAPI routers, request/response models, and unit/integration test suites.",
                "target_files": ["src/api/routes.py", "tests/test_api.py"],
                "acceptance_criteria": ["Endpoints return 200 OK with valid schemas", "Test suite passes with >= 80% coverage"],
                "dependencies": ["TASK-03"],
                "pattern_refs": ["Router"],
                "requirement_refs": req_ids,
                "order_index": 4,
                "status": "pending"
            }
        ]

    # Validate DAG (sanitize dependencies to prevent cycles/forward refs)
    is_valid, errors, sorted_ids = validate_task_dag(tasks_raw)
    if not is_valid:
        logger.warning(f"Planner raw tasks contained DAG issues: {errors}. Auto-sanitizing dependencies.")
        seen_tids = set()
        for idx, t in enumerate(tasks_raw):
            tid = t["task_id"]
            # Filter dependencies to only allow tasks that appeared before this index
            t["dependencies"] = [d for d in t.get("dependencies", []) if d in seen_tids and d != tid]
            t["order_index"] = idx + 1
            seen_tids.add(tid)

    # Save artifact tasks.json
    runs_dir = file_store.get_runs_dir(project_id, run_id)
    with open(runs_dir / "tasks.json", "w", encoding="utf-8") as f:
        json.dump({"tasks": tasks_raw}, f, indent=2)

    await event_hub.publish(project_id, run_id, "node_completed", {
        "node": "planner",
        "task_count": len(tasks_raw)
    })

    return {
        "tasks": tasks_raw,
        "current_node": "planner"
    }


# ==========================================
# 6. Critic Node (Evaluator-Optimizer Loop)
# ==========================================
async def critic_node(state: PlanningGraphState) -> Dict[str, Any]:
    project_id = state["project_id"]
    run_id = state["run_id"]
    req_doc = state.get("requirements_doc", {})
    tasks = state.get("tasks", [])
    selected_patterns = state.get("selected_patterns", [])
    iterations = state.get("critic_iterations", 0) + 1

    logger.info(f"[{run_id}] Running critic_node (Iteration {iterations})")
    await event_hub.publish(project_id, run_id, "node_started", {"node": "critic", "iteration": iterations})

    func_reqs = req_doc.get("functional_requirements", [])
    req_ids = set([r.get("id") for r in func_reqs if r.get("id")])

    # Deterministic programmatic checks
    # 1. Coverage
    mapped_reqs = set()
    for t in tasks:
        for rref in t.get("requirement_refs", []):
            mapped_reqs.add(rref)
    missing_reqs = req_ids - mapped_reqs
    coverage_score = 2.5 if not missing_reqs else max(0.5, 2.5 * (len(mapped_reqs) / max(len(req_ids), 1)))

    # 2. Ordering & DAG validity
    is_valid_dag, dag_errors, _ = validate_task_dag(tasks)
    ordering_score = 2.5 if is_valid_dag else 0.5

    # 3. Pattern Fidelity
    pattern_names = set([p["pattern_name"] for p in selected_patterns])
    used_patterns = set()
    for t in tasks:
        for pref in t.get("pattern_refs", []):
            used_patterns.add(pref)
    fidelity_score = 2.5 if used_patterns.intersection(pattern_names) else 1.5

    # 4. Atomicity
    atomicity_score = 2.5
    for t in tasks:
        if len(t.get("target_files", [])) > 6:
            atomicity_score = 1.5

    total_score = round(coverage_score + ordering_score + fidelity_score + atomicity_score, 1)
    is_passing = total_score >= 8.0

    feedback_parts = []
    warnings = []
    if missing_reqs:
        feedback_parts.append(f"Missing coverage for requirements: {list(missing_reqs)}.")
    if dag_errors:
        feedback_parts.append(f"DAG ordering errors: {'; '.join(dag_errors)}.")
    if not is_passing:
        feedback_parts.append("Refine task breakdown to ensure atomicity and explicit pattern references.")

    critic_feedback = " ".join(feedback_parts) if feedback_parts else "Plan successfully passed all evaluation criteria."

    logger.info(f"[{run_id}] Critic score: {total_score}/10.0 (Passing: {is_passing})")
    await event_hub.publish(project_id, run_id, "node_completed", {
        "node": "critic",
        "iteration": iterations,
        "score": total_score,
        "is_passing": is_passing
    })

    return {
        "critic_score": total_score,
        "critic_feedback": critic_feedback if not is_passing else None,
        "critic_warnings": warnings,
        "critic_iterations": iterations,
        "current_node": "critic"
    }


# ==========================================
# 7. Approval Gate Node (HITL Interrupt)
# ==========================================
async def approval_gate_node(state: PlanningGraphState) -> Dict[str, Any]:
    project_id = state["project_id"]
    run_id = state["run_id"]
    tasks = state.get("tasks", [])
    arch = state.get("architecture", {})
    score = state.get("critic_score", 10.0)
    warnings = state.get("critic_warnings", [])

    logger.info(f"[{run_id}] Pausing at Planning Approval Gate")

    req_id = str(uuid.uuid4())
    approval_payload = {
        "type": "approval_request",
        "request_id": req_id,
        "artifact": {
            "architecture_md_url": f"/projects/{project_id}/runs/{run_id}/artifacts/architecture.md",
            "architecture_json_url": f"/projects/{project_id}/runs/{run_id}/artifacts/architecture.json",
            "tasks_json_url": f"/projects/{project_id}/runs/{run_id}/artifacts/tasks.json",
            "research_json_url": f"/projects/{project_id}/runs/{run_id}/artifacts/research.json",
            "patterns_report_url": f"/projects/{project_id}/runs/{run_id}/artifacts/patterns_report.json",
            "task_count": len(tasks),
            "critic_score": score,
            "warnings": warnings,
            "summary": f"Generated plan with {len(tasks)} code-ready tasks. Critic score: {score}/10."
        }
    }

    await event_hub.publish(project_id, run_id, "approval_requested", approval_payload)

    # LangGraph Interrupt: Pauses execution until client approves or rejects
    user_decision = interrupt(approval_payload)

    decision = "approve"
    feedback = None
    if isinstance(user_decision, dict):
        decision = user_decision.get("decision", "approve")
        feedback = user_decision.get("feedback")

    logger.info(f"[{run_id}] Resumed from approval gate with decision: '{decision}', feedback: '{feedback}'")

    return {
        "approval_status": decision,
        "user_feedback": feedback,
        "current_node": "approval_gate"
    }


# ==========================================
# 8. Complete Node
# ==========================================
async def complete_node(state: PlanningGraphState) -> Dict[str, Any]:
    project_id = state["project_id"]
    run_id = state["run_id"]
    tasks = state.get("tasks", [])
    architecture = state.get("architecture", {})

    # Check for human edits / splits / reorderings from artifacts on disk
    runs_dir = file_store.get_runs_dir(project_id, run_id)
    tasks_file = runs_dir / "tasks.json"
    if tasks_file.exists():
        try:
            with open(tasks_file, "r", encoding="utf-8") as f:
                disk_data = json.load(f)
                if disk_data.get("tasks"):
                    tasks = disk_data["tasks"]
        except Exception as e:
            logger.warning(f"[{run_id}] Failed reading tasks.json in complete_node: {e}")

    arch_file = runs_dir / "architecture.json"
    if arch_file.exists():
        try:
            with open(arch_file, "r", encoding="utf-8") as f:
                disk_arch = json.load(f)
                if disk_arch:
                    architecture = disk_arch
        except Exception as e:
            logger.warning(f"[{run_id}] Failed reading architecture.json in complete_node: {e}")

    logger.info(f"[{run_id}] Running complete_node. Persisting {len(tasks)} tasks to DB.")

    async with db_module.AsyncSessionLocal() as session:
        from sqlalchemy import select, delete
        # Delete any previous tasks for this run (idempotent overwrite)
        await session.execute(delete(Task).where(Task.run_id == run_id))

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
                order_index=idx + 1,
                status="pending"
            )
            session.add(db_task)

        # Update run status to completed
        r_res = await session.execute(select(Run).where(Run.id == run_id))
        r = r_res.scalar_one_or_none()
        if r:
            r.status = "completed"
            r.completed_at = datetime.now(timezone.utc)
            r.output_data = {
                "tasks_count": len(tasks),
                "architecture": architecture
            }

        # Update project status to ready (ready for codegen)
        p_res = await session.execute(select(Project).where(Project.id == project_id))
        p = p_res.scalar_one_or_none()
        if p:
            p.status = "ready"

        await session.commit()

    await event_hub.publish(project_id, run_id, "run_completed", {
        "status": "completed",
        "decision": "approved",
        "tasks_count": len(tasks),
        "artifacts": ["architecture.md", "architecture.json", "tasks.json", "research.json", "patterns_report.json"]
    })

    return {
        "approval_status": "approved",
        "tasks": tasks,
        "current_node": "complete"
    }


# ==========================================
# 9. Feedback Router Node (Adaptive Re-entry)
# ==========================================
async def feedback_router_node(state: PlanningGraphState) -> Dict[str, Any]:
    project_id = state["project_id"]
    run_id = state["run_id"]
    feedback = state.get("user_feedback", "") or ""

    logger.info(f"[{run_id}] Running feedback_router_node on feedback: '{feedback}'")
    await event_hub.publish(project_id, run_id, "node_started", {"node": "feedback_router"})

    fb_lower = feedback.lower()

    # Scope 1: Pattern-level keywords
    pattern_keywords = ["pattern", "patterns", "react", "reflexion", "rag", "planner-executor", "tool-use", "agent pattern", "design pattern"]
    # Scope 2: Architecture-level keywords
    arch_keywords = ["architecture", "component", "topology", "database", "redis", "framework", "redesign", "data flow", "deployment"]
    # Scope 3: Task-level keywords
    task_keywords = ["task", "split", "reorder", "criteria", "acceptance", "file", "dependency", "dag"]

    if any(k in fb_lower for k in pattern_keywords) and not any(k in fb_lower for k in task_keywords):
        target = "pattern_selector"
    elif any(k in fb_lower for k in arch_keywords) and not any(k in fb_lower for k in task_keywords):
        target = "architect"
    else:
        target = "planner"

    logger.info(f"[{run_id}] Feedback re-entry targeted to: '{target}'")
    await event_hub.publish(project_id, run_id, "node_completed", {
        "node": "feedback_router",
        "target": target
    })

    return {
        "reentry_node": target,
        "current_node": "feedback_router"
    }


# ==========================================
# Graph Builder & Routing Conditions
# ==========================================
def should_evaluate_critic(state: PlanningGraphState) -> str:
    path = state.get("complexity_path", "heavyweight")
    if path == "lightweight":
        return "approval_gate"
    return "critic"


def critic_decision(state: PlanningGraphState) -> str:
    score = state.get("critic_score", 0.0)
    iterations = state.get("critic_iterations", 0)

    if score >= 8.0 or iterations >= 3:
        return "approval_gate"
    return "planner"


def approval_decision(state: PlanningGraphState) -> str:
    status = state.get("approval_status", "pending")
    if status == "approve":
        return "complete"
    return "feedback_router"


def feedback_reentry_decision(state: PlanningGraphState) -> str:
    return state.get("reentry_node", "planner")


def build_planning_graph() -> StateGraph:
    builder = StateGraph(PlanningGraphState)

    builder.add_node("complexity_router", complexity_router_node)
    builder.add_node("pattern_selector", pattern_selector_node)
    builder.add_node("researcher_subgraph", researcher_subgraph_node)
    builder.add_node("architect", architect_node)
    builder.add_node("planner", planner_node)
    builder.add_node("critic", critic_node)
    builder.add_node("approval_gate", approval_gate_node)
    builder.add_node("complete", complete_node)
    builder.add_node("feedback_router", feedback_router_node)

    # Edges
    builder.add_edge(START, "complexity_router")
    builder.add_edge("complexity_router", "pattern_selector")
    builder.add_edge("pattern_selector", "researcher_subgraph")
    builder.add_edge("researcher_subgraph", "architect")
    builder.add_edge("architect", "planner")

    # Conditional edge after planner: lightweight -> approval_gate, heavyweight -> critic
    builder.add_conditional_edges(
        "planner",
        should_evaluate_critic,
        {
            "approval_gate": "approval_gate",
            "critic": "critic"
        }
    )

    # Conditional edge after critic: passing or cap exceeded -> approval_gate, else loop to planner
    builder.add_conditional_edges(
        "critic",
        critic_decision,
        {
            "approval_gate": "approval_gate",
            "planner": "planner"
        }
    )

    # Conditional edge after approval_gate: approved -> complete, rejected -> feedback_router
    builder.add_conditional_edges(
        "approval_gate",
        approval_decision,
        {
            "complete": "complete",
            "feedback_router": "feedback_router"
        }
    )

    # Conditional edge after feedback_router: re-enters pattern_selector, architect, or planner
    builder.add_conditional_edges(
        "feedback_router",
        feedback_reentry_decision,
        {
            "pattern_selector": "pattern_selector",
            "architect": "architect",
            "planner": "planner"
        }
    )

    builder.add_edge("complete", END)

    return builder
