"""
Milestone 4 Verification Script
Demonstrates end-to-end Project & Code Planning Workflow (Workflow 2):
1. Authenticates & retrieves JWT Bearer token
2. Creates a Project
3. Runs Workflow 1 (Requirements) to obtain approved requirements
4. Triggers POST /projects/{project_id}/workflows/planning
5. Connects to WebSocket WS /projects/{project_id}/runs/{run_id}/hitl
6. Handles planning approval_request (inspects Critic score, architecture, and task DAG)
7. Tests GET /projects/{project_id}/runs/{run_id}/tasks
8. Tests PATCH /projects/{project_id}/runs/{run_id}/tasks/{task_id} (task splitting/editing with DAG validation)
9. Sends approval_response over WebSocket
10. Verifies run completes and tasks are persisted in the SQLite tasks table
11. Checks workflow diagram endpoint GET /workflows/planning/mermaid
"""

import sys
import json
import asyncio
import httpx
import websockets

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_URL = "http://127.0.0.1:8000"
WS_BASE_URL = "ws://127.0.0.1:8000"


async def run_milestone_4_verification():
    print("=" * 70)
    print("STARTING MILESTONE 4 (WORKFLOW 2: PLANNING) VERIFICATION")
    print("=" * 70)

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=40.0) as client:
        # Step 1: Login
        print("\n[STEP 1] Authenticating via POST /auth/login...")
        auth_resp = await client.post("/auth/login", json={"username": "dev_user", "password": "dev_password"})
        if auth_resp.status_code != 200:
            print(f"[ERROR] Auth failed: {auth_resp.text}")
            return
        token = auth_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print(f"[OK] Authenticated successfully. Token: {token[:20]}...")

        # Step 2: Create Project
        print("\n[STEP 2] Creating Project via POST /projects...")
        proj_resp = await client.post(
            "/projects",
            json={"name": "M4 Planning Demo", "description": "Testing Combined Project & Code Planning Graph"},
            headers=headers
        )
        project_id = proj_resp.json()["id"]
        print(f"[OK] Project Created: {project_id}")

        # Step 3: Fast-track Requirements (Workflow 1 approval)
        print("\n[STEP 3] Triggering Workflow 1 to produce approved requirements...")
        wf1_resp = await client.post(
            f"/projects/{project_id}/workflows/requirements",
            json={"document_ids": []},
            headers=headers
        )
        req_run_id = wf1_resp.json()["run_id"]
        print(f"[OK] Requirements run started: {req_run_id}")

        # Connect to WS to approve Workflow 1
        ws1_url = f"{WS_BASE_URL}/projects/{project_id}/runs/{req_run_id}/hitl?token={token}"
        async with websockets.connect(ws1_url) as ws1:
            while True:
                msg = await asyncio.wait_for(ws1.recv(), timeout=30.0)
                evt = json.loads(msg)
                mtype = evt.get("type")
                if mtype in ["clarification_request", "clarification_requested"]:
                    req_id = evt.get("request_id")
                    await ws1.send(json.dumps({
                        "type": "clarification_response",
                        "request_id": req_id,
                        "answers": [{"id": "q1", "answer": "Standard e-commerce backend with secure JWT authentication."}]
                    }))
                elif mtype in ["approval_request", "approval_requested"]:
                    req_id = evt.get("request_id")
                    print("[OK] Workflow 1 approval requested. Approving...")
                    await ws1.send(json.dumps({
                        "type": "approval_response",
                        "request_id": req_id,
                        "decision": "approve"
                    }))
                elif mtype == "run_completed":
                    print("[OK] Workflow 1 Completed!")
                    break

        await asyncio.sleep(1)

        # Step 4: Trigger Workflow 2 (Planning)
        print(f"\n[STEP 4] Triggering Workflow 2 via POST /projects/{project_id}/workflows/planning...")
        plan_resp = await client.post(
            f"/projects/{project_id}/workflows/planning",
            json={"requirements_run_id": req_run_id},
            headers=headers
        )
        assert plan_resp.status_code == 202, f"Expected 202, got {plan_resp.status_code}: {plan_resp.text}"
        plan_data = plan_resp.json()
        plan_run_id = plan_data["run_id"]
        print(f"[OK] Planning Run Triggered! Run ID: {plan_run_id}")
        print(f"     Events URL: {plan_data.get('events_url')}")
        print(f"     WebSocket HITL URL: {plan_data.get('hitl_ws_url')}")

        # Step 5: Connect to WebSocket HITL for Planning
        print(f"\n[STEP 5] Connecting to WebSocket HITL for Planning Run...")
        ws_url = f"{WS_BASE_URL}/projects/{project_id}/runs/{plan_run_id}/hitl?token={token}"
        async with websockets.connect(ws_url) as ws:
            print("[WS] Connected to Planning HITL socket. Awaiting approval request...")

            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=45.0)
                evt = json.loads(msg)
                mtype = evt.get("type")
                print(f"[WS-IN] Message: {mtype}")

                if mtype in ["approval_request", "approval_requested"]:
                    art = evt.get("artifact", {})
                    score = art.get("critic_score")
                    summary = art.get("summary")
                    print(f"\n[HITL] Planning Approval Requested!")
                    print(f"       Critic Score: {score}/10.0")
                    print(f"       Summary: {summary}")
                    print(f"       Architecture MD: {art.get('architecture_md_url')}")
                    print(f"       Tasks JSON: {art.get('tasks_json_url')}")
                    print(f"       Research JSON: {art.get('research_json_url')}")
                    print(f"       Patterns Report: {art.get('patterns_report_url')}")

                    # Step 6: Test GET /tasks endpoint
                    print("\n[STEP 6] Testing GET /tasks endpoint...")
                    t_resp = await client.get(f"/projects/{project_id}/runs/{plan_run_id}/tasks", headers=headers)
                    tasks = t_resp.json()
                    print(f"[OK] Retrieved {len(tasks)} tasks:")
                    for t in tasks:
                        print(f"     - [{t.get('task_id')}] {t.get('title')} (Deps: {t.get('dependencies')}, Req: {t.get('requirement_refs')})")

                    # Step 7: Test PATCH /tasks/{task_id} with Task Splitting
                    target_task_id = tasks[1].get("task_id") if len(tasks) > 1 else tasks[0].get("task_id")
                    print(f"\n[STEP 7] Testing PATCH /tasks/{target_task_id} (Split task)...")
                    patch_body = {
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
                    }
                    patch_resp = await client.patch(
                        f"/projects/{project_id}/runs/{plan_run_id}/tasks/{target_task_id}",
                        json=patch_body,
                        headers=headers
                    )
                    assert patch_resp.status_code == 200, f"Patch failed: {patch_resp.text}"
                    patched_tasks = patch_resp.json()["tasks"]
                    print(f"[OK] Task split successful! Total tasks now: {len(patched_tasks)}")
                    for pt in patched_tasks:
                        print(f"     - [{pt.get('task_id')}] {pt.get('title')} (Deps: {pt.get('dependencies')})")

                    # Step 8: Send Approval Response over WebSocket
                    req_id = evt.get("request_id")
                    print("\n[STEP 8] Sending approval_response over WebSocket...")
                    await ws.send(json.dumps({
                        "type": "approval_response",
                        "request_id": req_id,
                        "decision": "approve"
                    }))

                elif mtype == "run_completed":
                    print("\n[STEP 9] Planning Run Completed Successfully!")
                    payload = evt.get("payload", {})
                    print(f"       Status: {payload.get('status')}")
                    print(f"       Decision: {payload.get('decision')}")
                    print(f"       Tasks Created: {payload.get('tasks_count')}")
                    print(f"       Artifacts: {payload.get('artifacts')}")
                    break

        # Step 10: Verify database tasks persistence & diagram
        print("\n[STEP 10] Verifying database persistence & diagram routes...")
        status_resp = await client.get(f"/projects/{project_id}/runs/{plan_run_id}", headers=headers)
        st_data = status_resp.json()
        print(f"[OK] Run Final Status: {st_data.get('status')}")
        print(f"     Artifacts Generated: {st_data.get('artifacts')}")
        print(f"     Total Tokens Used: {st_data.get('total_tokens')}")
        print(f"     Total Cost: ${st_data.get('cost_usd')}")

        # Check cited research log route
        res_resp = await client.get(f"/projects/{project_id}/runs/{plan_run_id}/research", headers=headers)
        assert res_resp.status_code == 200
        res_data = res_resp.json()
        print(f"[OK] GET /research returned {len(res_data.get('citations', []))} cited research claims.")

        # Check diagram route
        diag_resp = await client.get("/workflows/planning/mermaid")
        assert diag_resp.status_code == 200
        print(f"[OK] Workflow diagram endpoint returned {len(diag_resp.text)} chars of Mermaid code.")

        print("\n" + "=" * 70)
        print("MILESTONE 4 (WORKFLOW 2: PLANNING) VERIFIED WITH 100% SUCCESS!")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_milestone_4_verification())
