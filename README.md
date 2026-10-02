# AI Agent Factory v2: Document-Driven, Pattern-Aware Code Generator

A production-grade, backend-only AI Agent Factory that ingests business and technical specifications (BRD / PRD / TRD in PDF, DOCX, PPTX, XLSX, MD, TXT) and autonomously drives three sequential agentic workflows to produce a working, pattern-aware codebase.

Powered by an **Adaptive Multi-LLM Routing Engine** that decouples business logic from model providers and optimizes for zero-cost development while enabling target frontier backbones (GPT-5.4 / GPT-5.5) in production.

---

## Architecture Overview

```
[Business Documents] (PDF, DOCX, XLSX, PPTX, MD, TXT)
       │
       ▼
┌────────────────────────────────────────────────────────┐
│ Document Ingestion & Parsers                           │
│  - Heading-Aware Structured Section Extraction         │
│  - Project-Isolated Vector Embeddings (ChromaDB)       │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Pattern Knowledge Base (Global Curated Library)        │
│  - 10 Canonical Patterns Seeded on Startup             │
│  - Semantic Vector Search + Similarity Scores          │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Adaptive Multi-LLM Router                              │
│  - Task Capability Classifier                          │
│  - Provider Registry (OpenAI, Gemini, Groq, Ollama)   │
│  - Capability-Aware Fallback & Cooldown Engine         │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ 3 Autonomous Agentic Workflows                         │
│  1. Requirements Gathering (Reflection + HITL WS)      │
│  2. Combined Planning (RAG + Research + Critic Loop)   │
│  3. Code Generation (Dynamic Subgraphs + Reviewers)    │
└────────────────────────────────────────────────────────┘
```

---

## Quickstart Guide

### 1. Environment Setup
```powershell
cd C:/Users/venee/OneDrive/Desktop/HashedIn/agent_factory
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Run Test Suite
```powershell
.\.venv\Scripts\pytest.exe -v
```

### 3. Start Application Server
```powershell
.\.venv\Scripts\uvicorn.exe src.main:app --host 127.0.0.1 --port 8000 --reload
```
Interactive Swagger documentation is available at: **http://127.0.0.1:8000/docs**

---

## 📋 Milestone 2 Verification: Pattern Knowledge Base

Milestone 2 implements the curated Agentic Design Patterns Knowledge Base with dual persistence (SQLite + ChromaDB), 10 canonical seed patterns, single/bulk CRUD, and semantic search.

### Verification Steps & Sample Outputs:

#### Step 1: List All Patterns (Includes 10 Canonical Seeds)
```bash
curl -X GET http://127.0.0.1:8000/patterns \
  -H "Authorization: Bearer <TOKEN>"
```
**Sample Response:**
```json
{
  "patterns": [
    {
      "id": "e44d73aa-e129-57e0-9494-0cf112a953e5",
      "name": "Critic-Refine (Reflexion)",
      "intent": "Advanced Evaluator-Optimizer pattern incorporating episodic memory of past attempts...",
      "structure": "Agent attempts task -> Evaluator runs deterministic checks...",
      "when_to_use": "Automated test-driven code generation, solving competitive programming tasks...",
      "when_not_to_use": "Open-ended tasks without verifiable tests...",
      "prerequisites": ["Deterministic validation harness", "Episodic reflection memory list in state"],
      "references": ["https://arxiv.org/abs/2303.11366"],
      "tags": ["reflexion", "evaluator-optimizer", "self-correction", "memory"],
      "created_at": "2026-09-09T11:18:00Z",
      "updated_at": "2026-09-09T11:18:00Z"
    },
    {
      "id": "b3ff30fb-9ce8-41cc-8c51-57b210d81a2d",
      "name": "Planner-Executor",
      "intent": "Separates high-level goal decomposition and strategic planning from granular task execution...",
      "structure": "Planner agent breaks user objective into an ordered, dependency-aware task list...",
      "when_to_use": "Long-horizon coding workflows, multi-step system architectures...",
      "when_not_to_use": "Simple single-intent requests...",
      "prerequisites": ["Pydantic structured schema", "Execution state store"],
      "references": ["LangGraph Plan-and-Execute Architecture"],
      "tags": ["plan-and-execute", "orchestration", "task-decomposition"],
      "created_at": "2026-09-09T11:18:00Z",
      "updated_at": "2026-09-09T11:18:00Z"
    }
  ],
  "total": 10
}
```

#### Step 2: Semantic Search Over Pattern KB
```bash
curl -X POST http://127.0.0.1:8000/patterns/search \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "I need an agent that decomposes goals into tasks and consumes them sequentially",
    "tags": ["plan-and-execute"],
    "top_k": 3
  }'
```
**Sample Response:**
```json
{
  "query": "I need an agent that decomposes goals into tasks and consumes them sequentially",
  "total_matched": 1,
  "results": [
    {
      "id": "b3ff30fb-9ce8-41cc-8c51-57b210d81a2d",
      "name": "Planner-Executor",
      "similarity_score": 0.7986,
      "matched_fields": ["intent", "when_to_use", "structure", "tags"],
      "pattern": {
        "id": "b3ff30fb-9ce8-41cc-8c51-57b210d81a2d",
        "name": "Planner-Executor",
        "intent": "Separates high-level goal decomposition and strategic planning from granular task execution...",
        "structure": "Planner agent breaks user objective into an ordered, dependency-aware task list...",
        "when_to_use": "Long-horizon coding workflows...",
        "when_not_to_use": "Simple single-intent requests...",
        "prerequisites": ["Pydantic structured schema", "Execution state store"],
        "references": ["LangGraph Plan-and-Execute Architecture"],
        "tags": ["plan-and-execute", "orchestration", "task-decomposition"],
        "created_at": "2026-09-09T11:18:00Z",
        "updated_at": "2026-09-09T11:18:00Z"
      }
    }
  ]
}
```

#### Step 3: Create Single Pattern
```bash
curl -X POST http://127.0.0.1:8000/patterns \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Guardrail-Validator",
    "intent": "Ensures all agent inputs and outputs pass strict safety and schema checks.",
    "structure": "Input -> Guardrail Node -> Core Agent -> Output Validator -> Final Response.",
    "when_to_use": "Strict enterprise compliance and safety applications.",
    "when_not_to_use": "Internal prototype exploration.",
    "prerequisites": ["Regex validator", "Schema filter"],
    "references": ["https://example.com/guardrails"],
    "tags": ["safety", "guardrail", "validation"]
  }'
```
**Sample Response (201 Created):**
```json
{
  "id": "92186835-236b-4eef-b0a3-380d3be07d4b",
  "name": "Guardrail-Validator",
  "intent": "Ensures all agent inputs and outputs pass strict safety and schema checks.",
  "structure": "Input -> Guardrail Node -> Core Agent -> Output Validator -> Final Response.",
  "when_to_use": "Strict enterprise compliance and safety applications.",
  "when_not_to_use": "Internal prototype exploration.",
  "prerequisites": ["Regex validator", "Schema filter"],
  "references": ["https://example.com/guardrails"],
  "tags": ["safety", "guardrail", "validation"],
  "created_at": "2026-09-09T11:20:00Z",
  "updated_at": "2026-09-09T11:20:00Z"
}
```

#### Step 4: Bulk Upload Patterns (JSON or YAML)
```bash
curl -X POST http://127.0.0.1:8000/patterns/bulk \
  -H "Authorization: Bearer <TOKEN>" \
  -F "file=@seeds/patterns.yaml"
```
**Sample Response (201 Created):**
```json
{
  "patterns": [ ... ],
  "total": 10
}
```

---

## Milestone 3: Workflow 1 (Requirements Gathering Agent)

### Architecture & Capabilities
- **Reflection / Self-Critique:** Discovers document gaps, ambiguities, and missing constraints.
- **LangGraph Checkpointing:** State persisted in SQLite (`./data/checkpoints.sqlite`) via `AsyncSqliteSaver`.
- **WebSocket HITL Channel:** Interactive interrupts for clarifications and spec approvals at `WS /projects/{project_id}/runs/{run_id}/hitl`.
- **Output Artifacts:** Dual canonical artifacts: Markdown specification (`requirements.md`) and Pydantic JSON schema (`requirements.json`).
- **REST Fallbacks:** Parity endpoints for scriptable CI/CD automation (`/clarifications`, `/approve`, `/reject`).

### 1-Click Verification Script
```bash
python scripts/verify_milestone_3.py
```

### Pytest Verification Suite
```bash
pytest tests/test_workflow_requirements.py -v
```

### Step-by-Step API & WebSocket Verification

#### 1. Trigger Requirements Gathering Workflow
```bash
curl -X POST http://127.0.0.1:8000/projects/<PROJECT_ID>/workflows/requirements \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"document_ids": []}'
```
**Response (`202 Accepted`):**
```json
{
  "run_id": "47329549-c4a0-4035-ab3c-d3072efb7310",
  "project_id": "<PROJECT_ID>",
  "workflow": "requirements",
  "status": "pending",
  "location": "/projects/<PROJECT_ID>/runs/47329549-c4a0-4035-ab3c-d3072efb7310",
  "events_url": "/projects/<PROJECT_ID>/runs/47329549-c4a0-4035-ab3c-d3072efb7310/events",
  "hitl_ws_url": "/projects/<PROJECT_ID>/runs/47329549-c4a0-4035-ab3c-d3072efb7310/hitl"
}
```

#### 2. Connect to WebSocket HITL Channel
Open a WebSocket connection to:
```
ws://127.0.0.1:8000/projects/<PROJECT_ID>/runs/<RUN_ID>/hitl?token=<TOKEN>
```
**Server Pushes `clarification_request`:**
```json
{
  "type": "clarification_request",
  "request_id": "req-uuid-123",
  "questions": [
    {"id": "q1", "question": "What is the expected persistence engine?"}
  ]
}
```
**Client Responds with `clarification_response`:**
```json
{
  "type": "clarification_response",
  "request_id": "req-uuid-123",
  "answers": [
    {"id": "q1", "answer": "FastAPI with SQLite and ChromaDB vector store."}
  ]
}
```

**Server Pushes `approval_request` (when specification is synthesized):**
```json
{
  "type": "approval_request",
  "request_id": "req-uuid-456",
  "artifact": {
    "requirements_md": "/data/projects/<PROJECT_ID>/runs/<RUN_ID>/requirements.md",
    "requirements_json": "/data/projects/<PROJECT_ID>/runs/<RUN_ID>/requirements.json"
  }
}
```
**Client Responds with `approval_response`:**
```json
{
  "type": "approval_response",
  "request_id": "req-uuid-456",
  "decision": "approve"
}
```

#### 3. Inspect Run Status & Cost Breakdown
```bash
curl -X GET http://127.0.0.1:8000/projects/<PROJECT_ID>/runs/<RUN_ID> \
  -H "Authorization: Bearer <TOKEN>"
```

---

## Milestone 4: Workflow 2 (Combined Project & Code Planning Multi-Agent Graph)

### Architecture & Capabilities
- **Orchestrator-Worker / Supervisor Topology:** Top-level multi-agent graph coordinating specialist agents:
  - **Complexity Router:** Directs projects to either a lightweight path ($< 3$ requirements) or a full heavyweight planning path ($\ge 3$ requirements).
  - **Pattern Selector:** Queries ChromaDB Pattern Knowledge Base using requirements context, selects minimal best-fit agent patterns with rationales, and snapshots them into the DB run record (`snapshotted_patterns`).
  - **Parallel Multi-Source Researcher:** Fans out into 3 parallel retrieval branches:
    1. *Document RAG* (filtered by `project_id` in ChromaDB `documents`)
    2. *Pattern KB RAG* (ChromaDB `patterns`)
    3. *Web Search* (DuckDuckGo Search Adapter with grounded synthetic fallback)
    - Synthesizes findings with verified citation tags: `[doc:section_id]`, `[kb:pattern_name]`, `[web:url]`, and `[llm]`.
  - **Architect Agent:** Generates system architecture (`architecture.md` and `architecture.json`) detailing components, data flow, agent topology, tool inventory, deployment, and risks with citations.
  - **Planner Agent:** Compiles architecture into an ordered, code-ready task DAG (`tasks.json`) with acceptance criteria, dependencies, pattern references, and requirement traceability IDs.
  - **Critic Agent (Evaluator-Optimizer Loop):** Validates task plan against a 4-subscore rubric (Coverage, Ordering, Pattern Fidelity, Atomicity) with an $8.0/10.0$ passing threshold and 3-iteration cap.
  - **Approval Gate (HITL over WebSocket):** Interactive `interrupt()` pausing for user review at `WS /projects/{project_id}/runs/{run_id}/hitl`.
  - **Adaptive Re-Entry Loop:** On rejection with feedback, intelligently routes re-entry back to the `planner` or `architect` without restarting from scratch.
- **First-Class SQLite `tasks` Table:** Stores task definitions and dependencies for downstream execution in Milestone 5.
- **Task Mutation API with DAG Validation:** `PATCH /projects/{project_id}/runs/{run_id}/tasks/{task_id}` supports editing, splitting, and reordering with cycle and forward-dependency detection (Kahn's algorithm).
- **Workflow Diagram Visualization:** Endpoints `GET /workflows/planning/mermaid` and `GET /workflows/planning/graph.png`.

### 1-Click Verification Script
```bash
python scripts/verify_milestone_4.py
```

### Pytest Verification Suite
```bash
pytest tests/test_workflow_planning.py -v
```

### Step-by-Step API & WebSocket Walkthrough

#### 1. Trigger Planning Workflow
```bash
curl -X POST http://127.0.0.1:8000/projects/<PROJECT_ID>/workflows/planning \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"requirements_run_id": "<REQUIREMENTS_RUN_ID>"}'
```
**Response (`202 Accepted`):**
```json
{
  "run_id": "65508b35-3ec2-49eb-bf63-878bd9066a5d",
  "project_id": "<PROJECT_ID>",
  "workflow": "planning",
  "status": "pending",
  "location": "/projects/<PROJECT_ID>/runs/65508b35-3ec2-49eb-bf63-878bd9066a5d",
  "events_url": "/projects/<PROJECT_ID>/runs/65508b35-3ec2-49eb-bf63-878bd9066a5d/events",
  "hitl_ws_url": "/projects/<PROJECT_ID>/runs/65508b35-3ec2-49eb-bf63-878bd9066a5d/hitl"
}
```

#### 2. Connect to WebSocket HITL Channel
Open a WebSocket connection to:
```
ws://127.0.0.1:8000/projects/<PROJECT_ID>/runs/<RUN_ID>/hitl?token=<TOKEN>
```
**Server Pushes `approval_request` with Plan Artifacts & Critic Score:**
```json
{
  "type": "approval_request",
  "request_id": "req-uuid-789",
  "artifact": {
    "architecture_md_url": "/projects/<PROJECT_ID>/runs/<RUN_ID>/artifacts/architecture.md",
    "architecture_json_url": "/projects/<PROJECT_ID>/runs/<RUN_ID>/artifacts/architecture.json",
    "tasks_json_url": "/projects/<PROJECT_ID>/runs/<RUN_ID>/artifacts/tasks.json",
    "research_json_url": "/projects/<PROJECT_ID>/runs/<RUN_ID>/artifacts/research.json",
    "patterns_report_url": "/projects/<PROJECT_ID>/runs/<RUN_ID>/artifacts/patterns_report.json",
    "task_count": 4,
    "critic_score": 10.0,
    "summary": "Generated plan with 4 code-ready tasks. Critic score: 10.0/10."
  }
}
```

#### 3. Inspect & Edit Tasks via REST Before Approving
**Retrieve Task List:**
```bash
curl -X GET http://127.0.0.1:8000/projects/<PROJECT_ID>/runs/<RUN_ID>/tasks \
  -H "Authorization: Bearer <TOKEN>"
```

**Split a Task into Subtasks:**
```bash
curl -X PATCH http://127.0.0.1:8000/projects/<PROJECT_ID>/runs/<RUN_ID>/tasks/TASK-02 \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "split",
    "split_into": [
      {
        "title": "Database Schema & Entity Definitions",
        "target_files": ["src/storage/schema.py"],
        "dependencies": []
      },
      {
        "title": "Database Migration & Seed Script",
        "target_files": ["src/storage/seed.py"],
        "dependencies": []
      }
    ]
  }'
```

#### 4. Approve or Reject Plan over WebSocket
**Approve Plan:**
```json
{
  "type": "approval_response",
  "request_id": "req-uuid-789",
  "decision": "approve"
}
```

**Reject Plan with Feedback (Triggers Adaptive Re-entry):**
```json
{
  "type": "approval_response",
  "request_id": "req-uuid-789",
  "decision": "reject",
  "feedback": "Split Task 2 and add unit tests to acceptance criteria."
}
```

#### 5. Render Workflow Diagram
```bash
curl -X GET http://127.0.0.1:8000/workflows/planning/mermaid
```

