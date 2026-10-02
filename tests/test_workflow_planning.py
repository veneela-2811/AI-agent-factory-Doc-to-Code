import pytest
import json
import uuid
from typing import Dict, Any

from src.workflows.planning.dag import validate_task_dag, split_task, DAGValidationError
from src.workflows.planning.schemas import (
    SystemArchitecture, ArchitectureComponent, TaskItem, TaskPlan, CriticRubric
)
from src.workflows.planning.graph import (
    complexity_router_node,
    pattern_selector_node,
    researcher_subgraph_node,
    architect_node,
    planner_node,
    critic_node,
    feedback_router_node,
    build_planning_graph
)


def test_dag_cycle_detection():
    # Valid DAG
    valid_tasks = [
        {"task_id": "TASK-01", "dependencies": []},
        {"task_id": "TASK-02", "dependencies": ["TASK-01"]},
        {"task_id": "TASK-03", "dependencies": ["TASK-01", "TASK-02"]},
    ]
    is_valid, errors, sorted_ids = validate_task_dag(valid_tasks)
    assert is_valid is True
    assert len(errors) == 0
    assert sorted_ids == ["TASK-01", "TASK-02", "TASK-03"]

    # Circular cycle
    cycle_tasks = [
        {"task_id": "TASK-01", "dependencies": ["TASK-02"]},
        {"task_id": "TASK-02", "dependencies": ["TASK-01"]},
    ]
    is_valid, errors, _ = validate_task_dag(cycle_tasks)
    assert is_valid is False
    assert any("Circular dependency" in e or "Forward dependency" in e for e in errors)

    # Forward dependency
    forward_tasks = [
        {"task_id": "TASK-01", "dependencies": ["TASK-02"]},
        {"task_id": "TASK-02", "dependencies": []},
    ]
    is_valid, errors, _ = validate_task_dag(forward_tasks)
    assert is_valid is False
    assert any("Forward dependency" in e for e in errors)


def test_dag_split_task():
    tasks = [
        {"task_id": "TASK-01", "title": "Setup", "dependencies": []},
        {"task_id": "TASK-02", "title": "Implement Backend & Frontend", "dependencies": ["TASK-01"]},
        {"task_id": "TASK-03", "title": "Deploy", "dependencies": ["TASK-02"]},
    ]

    split_into = [
        {"task_id": "TASK-02-A", "title": "Backend API", "dependencies": ["TASK-01"]},
        {"task_id": "TASK-02-B", "title": "Frontend UI", "dependencies": ["TASK-02-A"]}
    ]

    new_tasks = split_task(tasks, "TASK-02", split_into)
    assert len(new_tasks) == 4
    task_ids = [t["task_id"] for t in new_tasks]
    assert task_ids == ["TASK-01", "TASK-02-A", "TASK-02-B", "TASK-03"]

    # Downstream TASK-03 should now depend on TASK-02-B
    t3 = next(t for t in new_tasks if t["task_id"] == "TASK-03")
    assert "TASK-02-B" in t3["dependencies"]
    assert "TASK-02" not in t3["dependencies"]


@pytest.mark.asyncio
async def test_complexity_router_node():
    # Less than 3 requirements -> lightweight path
    state_simple = {
        "project_id": "p-1",
        "run_id": "r-1",
        "requirements_doc": {
            "functional_requirements": [
                {"id": "REQ-01", "title": "Login"},
                {"id": "REQ-02", "title": "Logout"}
            ]
        }
    }
    res_simple = await complexity_router_node(state_simple)
    assert res_simple["complexity_path"] == "lightweight"

    # 3 or more requirements -> heavyweight path
    state_complex = {
        "project_id": "p-1",
        "run_id": "r-1",
        "requirements_doc": {
            "functional_requirements": [
                {"id": "REQ-01", "title": "Auth"},
                {"id": "REQ-02", "title": "Payments"},
                {"id": "REQ-03", "title": "Reports"}
            ]
        }
    }
    res_complex = await complexity_router_node(state_complex)
    assert res_complex["complexity_path"] == "heavyweight"


@pytest.mark.asyncio
async def test_critic_node_evaluation():
    state = {
        "project_id": "p-1",
        "run_id": "r-1",
        "requirements_doc": {
            "functional_requirements": [
                {"id": "REQ-01", "title": "Search"},
                {"id": "REQ-02", "title": "Checkout"}
            ]
        },
        "selected_patterns": [{"pattern_name": "ReAct"}],
        "tasks": [
            {
                "task_id": "TASK-01",
                "dependencies": [],
                "requirement_refs": ["REQ-01"],
                "pattern_refs": ["ReAct"],
                "target_files": ["src/search.py"]
            },
            {
                "task_id": "TASK-02",
                "dependencies": ["TASK-01"],
                "requirement_refs": ["REQ-02"],
                "pattern_refs": ["ReAct"],
                "target_files": ["src/checkout.py"]
            }
        ],
        "critic_iterations": 0
    }
    res = await critic_node(state)
    assert res["critic_score"] >= 8.0
    assert res["critic_iterations"] == 1


@pytest.mark.asyncio
async def test_feedback_router_heuristic():
    # Task-level feedback
    task_state = {
        "project_id": "p-1",
        "run_id": "r-1",
        "user_feedback": "Please split task 2 and add unit tests to acceptance criteria"
    }
    task_res = await feedback_router_node(task_state)
    assert task_res["reentry_node"] == "planner"

    # Pattern-level feedback
    pattern_state = {
        "project_id": "p-1",
        "run_id": "r-1",
        "user_feedback": "Change the agent design pattern to Reflexion"
    }
    pattern_res = await feedback_router_node(pattern_state)
    assert pattern_res["reentry_node"] == "pattern_selector"

    # Architecture-level feedback
    arch_state = {
        "project_id": "p-1",
        "run_id": "r-1",
        "user_feedback": "Redesign component architecture and switch database to Redis"
    }
    arch_res = await feedback_router_node(arch_state)
    assert arch_res["reentry_node"] == "architect"


def test_planning_graph_compilation():
    builder = build_planning_graph()
    graph = builder.compile()
    nodes = list(graph.nodes.keys())
    assert "complexity_router" in nodes
    assert "pattern_selector" in nodes
    assert "researcher_subgraph" in nodes
    assert "architect" in nodes
    assert "planner" in nodes
    assert "critic" in nodes
    assert "approval_gate" in nodes
    assert "complete" in nodes
    assert "feedback_router" in nodes


@pytest.mark.asyncio
async def test_researcher_subgraph_citations():
    state = {
        "project_id": "test-p",
        "run_id": "test-r",
        "requirements_doc": {"overview": "E-commerce platform", "functional_requirements": []},
        "selected_patterns": [{"pattern_name": "ReAct"}]
    }
    res = await researcher_subgraph_node(state)
    findings = res["research_findings"]
    assert len(findings) > 0
    # Must have citation tags
    citation_tags = [f["citation_tag"] for f in findings]
    assert any("[llm]" in tag for tag in citation_tags)
    assert any("[web:" in tag for tag in citation_tags)


@pytest.mark.asyncio
async def test_feedback_router_three_tier_reentry():
    from src.workflows.planning.graph import feedback_router_node

    # Tier 1: Pattern feedback routes to pattern_selector
    res1 = await feedback_router_node({
        "project_id": "test-p", "run_id": "test-r",
        "user_feedback": "I do not like the ReAct pattern. Select Reflexion instead."
    })
    assert res1["reentry_node"] == "pattern_selector"

    # Tier 2: Architecture feedback routes to architect
    res2 = await feedback_router_node({
        "project_id": "test-p", "run_id": "test-r",
        "user_feedback": "Switch component architecture to Redis pubsub and microservices"
    })
    assert res2["reentry_node"] == "architect"

    # Tier 3: Task feedback routes to planner
    res3 = await feedback_router_node({
        "project_id": "test-p", "run_id": "test-r",
        "user_feedback": "Split TASK-02 into separate tasks and refine acceptance criteria"
    })
    assert res3["reentry_node"] == "planner"
