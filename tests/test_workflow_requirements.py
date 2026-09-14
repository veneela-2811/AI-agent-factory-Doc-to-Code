import pytest
import json
import asyncio
from pathlib import Path
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from src.storage.models import Project, Document, Run, Usage
from src.workflows.requirements.graph import build_requirements_graph
from src.workflows.requirements.schemas import RequirementsStructuredDoc, GapAnalysisResult
from src.workflows.runner import workflow_runner
from src.storage.filestore import file_store


@pytest.mark.asyncio
async def test_requirements_workflow_trigger_and_conflict(client: AsyncClient, auth_headers: dict):
    # 1. Create Project
    p_resp = await client.post("/projects", json={"name": "WF1 Trigger Test"}, headers=auth_headers)
    assert p_resp.status_code == 201
    project_id = p_resp.json()["id"]

    # 2. Trigger Requirements Workflow (202 Accepted)
    wf_resp = await client.post(
        f"/projects/{project_id}/workflows/requirements",
        json={"document_ids": []},
        headers=auth_headers
    )
    assert wf_resp.status_code == 202
    data = wf_resp.json()
    assert "run_id" in data
    assert data["status"] == "pending"
    assert "Location" in wf_resp.headers
    run_id = data["run_id"]

    # 3. Trigger second run on active project -> 409 Conflict
    dup_resp = await client.post(
        f"/projects/{project_id}/workflows/requirements",
        json={"document_ids": []},
        headers=auth_headers
    )
    assert dup_resp.status_code == 409
    assert dup_resp.json()["error"]["code"] == "RUN_ALREADY_ACTIVE"

    # 4. Check Run Status Endpoint
    status_resp = await client.get(f"/projects/{project_id}/runs/{run_id}", headers=auth_headers)
    assert status_resp.status_code == 200
    assert status_resp.json()["id"] == run_id


@pytest.mark.asyncio
async def test_requirements_state_machine_and_artifacts(test_db: AsyncSession, tmp_path: Path):
    project_id = "wf1-test-proj"
    run_id = "wf1-test-run"

    project = Project(id=project_id, name="State Machine Test", status="draft")
    run = Run(id=run_id, project_id=project_id, workflow_name="requirements", status="running")
    test_db.add(project)
    test_db.add(run)
    await test_db.commit()

    # Verify Graph nodes and compilation
    builder = build_requirements_graph()
    graph = builder.compile()

    state = {
        "project_id": project_id,
        "run_id": run_id,
        "document_ids": [],
        "document_chunks": [{
            "section_id": "sec_1",
            "title": "System Overview",
            "content": "Build an AI agent factory with LangGraph and SQLite."
        }],
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

    # Test spec synthesizer node directly
    from src.workflows.requirements.graph import spec_synthesizer_node
    syn_result = await spec_synthesizer_node(state)
    assert "requirements_md" in syn_result
    assert "requirements_json" in syn_result
    assert len(syn_result["requirements_md"]) > 50

    # Verify generated artifact files on disk
    runs_dir = file_store.get_runs_dir(project_id, run_id)
    assert (runs_dir / "requirements.md").exists()
    assert (runs_dir / "requirements.json").exists()


@pytest.mark.asyncio
async def test_rest_fallbacks_for_clarification_and_approval(client: AsyncClient, auth_headers: dict):
    p_resp = await client.post("/projects", json={"name": "Fallback REST Test"}, headers=auth_headers)
    project_id = p_resp.json()["id"]

    wf_resp = await client.post(
        f"/projects/{project_id}/workflows/requirements",
        json={"document_ids": []},
        headers=auth_headers
    )
    run_id = wf_resp.json()["run_id"]

    # Test submitting clarification answers via REST fallback
    clarify_resp = await client.post(
        f"/projects/{project_id}/runs/{run_id}/clarifications",
        json={"answers": [{"id": "q1", "answer": "Use PostgreSQL in cloud production"}]},
        headers=auth_headers
    )
    assert clarify_resp.status_code == 200
    assert clarify_resp.json()["status"] == "resumed"

    # Test rejection with feedback via REST fallback
    reject_resp = await client.post(
        f"/projects/{project_id}/runs/{run_id}/reject",
        json={"feedback": "Missing HIPAA compliance constraints"},
        headers=auth_headers
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected_with_feedback"

    # Test approval via REST fallback
    approve_resp = await client.post(
        f"/projects/{project_id}/runs/{run_id}/approve",
        headers=auth_headers
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"
