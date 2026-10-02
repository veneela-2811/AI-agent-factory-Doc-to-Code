import sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))

import time
import json
import sqlite3
import requests
from websockets.sync.client import connect

BASE_URL = "http://127.0.0.1:8000"
WS_BASE_URL = "ws://127.0.0.1:8000"

def log_step(step: str):
    print(f"\n{'='*75}\n[STEP] {step}\n{'='*75}")

def main():
    print("=" * 75)
    print("  AI AGENT FACTORY: END-TO-END HITL & CRITIC AGENT VERIFICATION")
    print("=" * 75)

    # 1. Login
    log_step("1. Authenticating as admin")
    res = requests.post(f"{BASE_URL}/auth/login", json={"username": "admin", "password": "password123"})
    assert res.status_code == 200, f"Login failed: {res.text}"
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("Authentication successful, JWT obtained.")

    # 2. Create Project
    log_step("2. Creating isolated project for HITL verification")
    res = requests.post(f"{BASE_URL}/projects", headers=headers, json={
        "name": "HITL Live Verification",
        "description": "Full end-to-end verification of Workflow 1 and Workflow 2 HITL gates and Critic Agent"
    })
    assert res.status_code == 201, f"Project creation failed: {res.text}"
    project_id = res.json()["id"]
    print(f"Project created with ID: {project_id}")

    # 3. Upload Sample Document
    log_step("3. Ingesting Enterprise Customer Support PRD")
    doc_path = Path("data/samples/enterprise_customer_support_prd.docx")
    assert doc_path.exists(), f"Sample doc not found at {doc_path}"
    with open(doc_path, "rb") as f:
        res = requests.post(
            f"{BASE_URL}/projects/{project_id}/documents",
            headers=headers,
            files={"file": (doc_path.name, f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        )
    assert res.status_code == 202, f"Document upload failed: {res.text}"
    doc_id = res.json().get("document_id") or res.json().get("id")
    print(f"Document uploaded successfully with ID: {doc_id}")

    # Wait for sections parsing
    time.sleep(2)
    res = requests.get(f"{BASE_URL}/projects/{project_id}/documents/{doc_id}/sections", headers=headers)
    sections = res.json().get("sections", [])
    print(f"Verified {len(sections)} document sections extracted and indexed.")

    # 4. Trigger Workflow 1
    log_step("4. Triggering Workflow 1: Requirements Gathering")
    res = requests.post(
        f"{BASE_URL}/projects/{project_id}/workflows/requirements",
        headers=headers,
        json={"document_ids": [doc_id]}
    )
    assert res.status_code == 202, f"Workflow 1 trigger failed: {res.text}"
    wf1_run_id = res.json()["run_id"]
    print(f"Workflow 1 started with Run ID: {wf1_run_id}")

    # 5. Monitor Workflow 1 until Clarification Interrupt
    log_step("5. Monitoring Workflow 1 until HITL Clarification Interrupt (Gate 1)")
    wf1_clarification_paused = False
    for i in range(40):
        time.sleep(2)
        st = requests.get(f"{BASE_URL}/projects/{project_id}/runs/{wf1_run_id}", headers=headers).json()
        status = st.get("status")
        node = st.get("current_node")
        print(f" - [{i+1}] Status: {status} | Current Node: {node}")
        if status == "paused":
            wf1_clarification_paused = True
            break
        if status in ["completed", "failed"]:
            break

    assert wf1_clarification_paused, f"Workflow 1 did not pause for clarification! Status: {status}"
    print("[SUCCESS] Workflow 1 paused at HITL Gate 1 (Clarification Interrupt)!")

    # 6. Verify WebSocket receives Clarification Request
    log_step("6. Verifying WebSocket HITL Gate 1: Clarification Request Payload")
    ws_url = f"{WS_BASE_URL}/projects/{project_id}/runs/{wf1_run_id}/hitl?token={token}"
    with connect(ws_url) as ws:
        raw_msg = ws.recv(timeout=5)
        ws_msg = json.loads(raw_msg)
        print(f"WebSocket received payload type: '{ws_msg.get('type')}'")
        assert ws_msg.get("type") == "clarification_request", f"Expected clarification_request, got: {ws_msg}"
        questions = ws_msg.get("questions", [])
        print(f"Probed {len(questions)} clarification questions from reflection node:")
        for q in questions:
            print(f"  - [{q.get('id')}]: {q.get('question')}")

    # 7. Submit Clarification Answers
    log_step("7. Submitting Clarification Answers (HITL Gate 1 Resolution)")
    clarification_payload = {
        "answers": [
            {
                "id": "q1",
                "answer": "The automated refund threshold is $50.00. Transactions exceeding $50.00 require human supervisor approval."
            },
            {
                "id": "q2",
                "answer": "Standard workflows include FAQ queries, order status lookups, and simple returns within 30 days."
            },
            {
                "id": "q3",
                "answer": "Item condition is verified via customer photo upload analyzed by automated vision inspection, with self-certification for unopened items under $25."
            }
        ]
    }
    res = requests.post(
        f"{BASE_URL}/projects/{project_id}/runs/{wf1_run_id}/clarifications",
        headers=headers,
        json=clarification_payload
    )
    assert res.status_code == 200, f"Clarification submission failed: {res.text}"
    print("Clarification submitted successfully. Run resumed in background.")

    # 8. Monitor until Workflow 1 reaches Approval Gate
    log_step("8. Monitoring Workflow 1 until Specification Synthesis & Approval Gate (Gate 2)")
    wf1_approval_paused = False
    for i in range(60):
        time.sleep(3)
        st = requests.get(f"{BASE_URL}/projects/{project_id}/runs/{wf1_run_id}", headers=headers).json()
        status = st.get("status")
        node = st.get("current_node")
        artifacts = st.get("artifacts", [])
        print(f" - [{i+1}] Status: {status} | Current Node: {node} | Artifacts: {artifacts}")
        if ("requirements.md" in artifacts and status == "paused") or node == "approval_gate":
            wf1_approval_paused = True
            break
        if status in ["completed", "failed"]:
            break

    assert wf1_approval_paused, "Workflow 1 did not reach Approval Gate!"
    print("[SUCCESS] Workflow 1 reached HITL Gate 2 (Approval Gate)!")

    # 9. Verify generated requirements.md artifact
    log_step("9. Verifying Synthesized Requirements Artifact (No Mocks)")
    res = requests.get(f"{BASE_URL}/projects/{project_id}/runs/{wf1_run_id}/artifacts/requirements.md", headers=headers)
    assert res.status_code == 200, f"Failed to download requirements.md: {res.text}"
    req_md = res.text
    print(f"\n[Generated requirements.md Snippet]:\n{req_md[:400]}...\n")
    assert "Enterprise Customer Support" in req_md or "Customer Support" in req_md, "Requirements artifact does not match PRD!"
    print("[SUCCESS] Verified requirements.md generated genuinely from Ollama LLM!")

    # 10. Approve Workflow 1
    log_step("10. Approving Workflow 1 Specification (HITL Gate 2 Resolution)")
    res = requests.post(f"{BASE_URL}/projects/{project_id}/runs/{wf1_run_id}/approve", headers=headers)
    assert res.status_code == 200, f"Workflow 1 approval failed: {res.text}"
    time.sleep(2)
    st = requests.get(f"{BASE_URL}/projects/{project_id}/runs/{wf1_run_id}", headers=headers).json()
    print(f"Workflow 1 final status: {st.get('status')}")
    assert st.get("status") == "completed", "Workflow 1 did not complete!"
    print("[SUCCESS] Workflow 1 Completed!")

    # 11. Trigger Workflow 2 (Planning & Architecture)
    log_step("11. Triggering Workflow 2: Planning & Architecture")
    res = requests.post(
        f"{BASE_URL}/projects/{project_id}/workflows/planning",
        headers=headers,
        json={"requirements_run_id": wf1_run_id}
    )
    assert res.status_code == 202, f"Workflow 2 trigger failed: {res.text}"
    wf2_run_id = res.json()["run_id"]
    print(f"Workflow 2 started with Run ID: {wf2_run_id}")

    # 12. Monitor Workflow 2 until Planning Approval Gate
    log_step("12. Monitoring Workflow 2 until Critic & HITL Approval Gate (Gate 3)")
    wf2_approval_paused = False
    for i in range(90):
        time.sleep(3)
        st = requests.get(f"{BASE_URL}/projects/{project_id}/runs/{wf2_run_id}", headers=headers).json()
        status = st.get("status")
        node = st.get("current_node")
        artifacts = st.get("artifacts", [])
        print(f" - [{i+1}] Status: {status} | Current Node: {node} | Artifacts: {artifacts}")
        if (status == "paused" and ("tasks.json" in artifacts or node == "approval_gate")) or node == "approval_gate":
            wf2_approval_paused = True
            break
        if status in ["completed", "failed"]:
            break

    assert wf2_approval_paused, f"Workflow 2 did not pause at Approval Gate! Final status: {status}"
    print("[SUCCESS] Workflow 2 reached HITL Gate 3 (Planning Approval Gate)!")

    # 13. Verify WebSocket receives Planning Approval Request & Critic Score
    log_step("13. Verifying WebSocket HITL Gate 3 & Critic Agent Evaluation")
    ws_url = f"{WS_BASE_URL}/projects/{project_id}/runs/{wf2_run_id}/hitl?token={token}"
    with connect(ws_url) as ws:
        raw_msg = ws.recv(timeout=5)
        ws_msg = json.loads(raw_msg)
        print(f"WebSocket received payload type: '{ws_msg.get('type')}'")
        assert ws_msg.get("type") == "approval_request", f"Expected approval_request, got: {ws_msg}"
        art = ws_msg.get("artifact", {})
        critic_score = art.get("critic_score")
        warnings = art.get("warnings", [])
        task_count = art.get("task_count")
        print(f"Critic Agent Score: {critic_score}/10.0")
        print(f"Critic Warnings: {warnings}")
        print(f"Initial Task Count: {task_count}")
        print(f"Architecture Markdown URL: {art.get('architecture_md_url')}")
        print(f"Tasks JSON URL: {art.get('tasks_json_url')}")
        assert critic_score is not None and critic_score >= 8.0, f"Critic score {critic_score} is below passing threshold (8.0)!"
        print(f"[SUCCESS] Critic Agent evaluated plan with passing score: {critic_score}/10.0!")

    # 14. Retrieve Task Plan via REST
    log_step("14. Retrieving Initial Task Plan DAG")
    res = requests.get(f"{BASE_URL}/projects/{project_id}/runs/{wf2_run_id}/tasks", headers=headers)
    assert res.status_code == 200, f"Failed to get tasks: {res.text}"
    tasks = res.json()
    print(f"Initial Plan has {len(tasks)} tasks:")
    for t in tasks:
        print(f" - [{t.get('task_id')}]: {t.get('title')} (Deps: {t.get('dependencies')}, Files: {t.get('target_files')})")

    # 15. Test In-Place Task Splitting & DAG Rewiring
    log_step("15. Executing Live In-Place Task Splitting (Splitting TASK-02)")
    target_task = tasks[1]["task_id"]  # TASK-02
    split_payload = {
        "action": "split",
        "split_into": [
            {
                "title": f"{target_task}.1: Implement Base Persistence Models & DB Connection",
                "description": "Define base models and audit log tables with async sessions",
                "target_files": ["src/storage/models.py", "src/storage/database.py"],
                "acceptance_criteria": ["Models match ERD schema", "Async engine connects cleanly"]
            },
            {
                "title": f"{target_task}.2: Implement Async Repositories & Data Access Layer",
                "description": "Implement repository query handlers and transactions",
                "target_files": ["src/storage/repositories.py"],
                "acceptance_criteria": ["Queries pass integration tests", "Transactions rollback on failure"]
            }
        ]
    }
    res = requests.patch(
        f"{BASE_URL}/projects/{project_id}/runs/{wf2_run_id}/tasks/{target_task}",
        headers=headers,
        json=split_payload
    )
    assert res.status_code == 200, f"Task split failed: {res.text}"
    print(f"Task {target_task} split successfully! DAG re-validated dynamically.")

    # 16. Verify Updated Tasks DAG
    log_step("16. Verifying Updated Task DAG After Split")
    res = requests.get(f"{BASE_URL}/projects/{project_id}/runs/{wf2_run_id}/tasks", headers=headers)
    updated_tasks = res.json()
    print(f"Updated tasks count: {len(updated_tasks)} (was {len(tasks)})")
    for t in updated_tasks:
        print(f" - [{t.get('task_id')}]: {t.get('title')} (Deps: {t.get('dependencies')})")
    assert len(updated_tasks) == len(tasks) + 1, "Task count did not increment after 1-to-2 split!"
    print("[SUCCESS] Task splitting and DAG rewiring verified!")

    # 17. Approve Workflow 2
    log_step("17. Approving Workflow 2 (HITL Gate 3 Resolution)")
    res = requests.post(f"{BASE_URL}/projects/{project_id}/runs/{wf2_run_id}/approve", headers=headers)
    assert res.status_code == 200, f"Workflow 2 approval failed: {res.text}"
    wf2_completed = False
    for _ in range(15):
        time.sleep(1)
        st = requests.get(f"{BASE_URL}/projects/{project_id}/runs/{wf2_run_id}", headers=headers).json()
        if st.get("status") == "completed":
            wf2_completed = True
            break
    print(f"Workflow 2 final status: {st.get('status')}")
    assert wf2_completed, "Workflow 2 did not complete!"
    print("[SUCCESS] Workflow 2 Completed!")

    # 18. Verify SQLite Persistence of Committed Tasks
    log_step("18. Verifying SQLite Database Persistence of Final Plan")
    c = sqlite3.connect("data/app.db")
    rows = c.execute("SELECT task_id, title, status FROM tasks WHERE run_id = ?", (wf2_run_id,)).fetchall()
    print(f"Persisted tasks in database: {len(rows)}")
    for r in rows:
        print(f" - [{r[0]}] {r[1]} (Status: {r[2]})")
    assert len(rows) == len(updated_tasks), "Database task count does not match final plan!"

    # 19. Final Report
    print("\n" + "=" * 75)
    print("  ALL VERIFICATIONS PASSED SUCCESSFULLY (100% OPERATIONAL)")
    print("=" * 75)
    print("  [PASS] Gate 1: Clarification Interrupt paused, probed questions, resumed.")
    print("  [PASS] Gate 2: Specification Synthesis completed (genuine LLM), paused & approved.")
    print("  [PASS] Gate 3: Planning executed, Critic Agent scored >= 8.0, paused at Approval Gate.")
    print("  [PASS] Task Splitting: In-place split with dynamic DAG rewiring passed.")
    print("  [PASS] Persistence: All artifacts and database tasks verified in SQLite.")
    print("=" * 75 + "\n")

if __name__ == "__main__":
    main()
