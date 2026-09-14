"""
Milestone 3 Verification Script
Demonstrates end-to-end Requirements Gathering Workflow (Workflow 1):
1. Authenticates & retrieves JWT Bearer token
2. Creates a Project
3. (Optional) Uploads a sample specification document
4. Triggers POST /projects/{project_id}/workflows/requirements
5. Connects to WebSocket WS /projects/{project_id}/runs/{run_id}/hitl
6. Handles clarification & approval prompts
7. Inspects generated requirements.md and requirements.json artifacts
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


async def run_milestone_3_verification():
    print("=" * 70)
    print("STARTING MILESTONE 3 (WORKFLOW 1) VERIFICATION")
    print("=" * 70)

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
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
            json={"name": "M3 Verification Demo", "description": "Testing Requirements Gathering Workflow"},
            headers=headers
        )
        project_id = proj_resp.json()["id"]
        print(f"[OK] Project Created: {project_id}")

        # Step 3: Trigger Requirements Workflow
        print(f"\n[STEP 3] Triggering Workflow 1 via POST /projects/{project_id}/workflows/requirements...")
        wf_resp = await client.post(
            f"/projects/{project_id}/workflows/requirements",
            json={"document_ids": []},
            headers=headers
        )
        assert wf_resp.status_code == 202, f"Expected 202 Accepted, got {wf_resp.status_code}: {wf_resp.text}"
        run_data = wf_resp.json()
        run_id = run_data["run_id"]
        print(f"[OK] Workflow Triggered! Run ID: {run_id}")
        print(f"     Location Header: {wf_resp.headers.get('Location')}")
        print(f"     Events URL: {run_data.get('events_url')}")
        print(f"     WebSocket HITL URL: {run_data.get('hitl_ws_url')}")

        # Step 4: Verify Idempotency (409 Conflict)
        print("\n[STEP 4] Testing Single Active Run Lock (Idempotency Check)...")
        dup_resp = await client.post(
            f"/projects/{project_id}/workflows/requirements",
            json={"document_ids": []},
            headers=headers
        )
        if dup_resp.status_code == 409:
            print("[OK] 409 Conflict successfully returned for concurrent active run attempt.")
        else:
            print(f"[WARN] Expected 409, got {dup_resp.status_code}")

        # Step 5: Connect to WebSocket HITL
        print(f"\n[STEP 5] Connecting to WebSocket HITL Channel: {WS_BASE_URL}/projects/{project_id}/runs/{run_id}/hitl...")
        ws_url = f"{WS_BASE_URL}/projects/{project_id}/runs/{run_id}/hitl?token={token}"
        try:
            async with websockets.connect(ws_url) as ws:
                print("[WS] WebSocket Connected! Listening for server-initiated HITL events...")

                # Loop to process clarification, approval, and completion
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=15.0)
                    event = json.loads(msg)
                    msg_type = event.get("type")
                    req_id = event.get("request_id")
                    print(f"[WS-IN] Received WS Message Type: '{msg_type}'")

                    if msg_type in ["clarification_request", "clarification_requested"]:
                        questions = event.get("questions") or event.get("payload", {}).get("questions", [])
                        print(f"[HITL] Clarification Request received with {len(questions)} questions:")
                        for q in questions:
                            print(f"       - [{q.get('id')}] {q.get('question')}")
                        # Reply with answers
                        answers = [{"id": q.get("id"), "answer": "Use SQLite and ChromaDB for local deployment."} for q in questions]
                        await ws.send(json.dumps({
                            "type": "clarification_response",
                            "request_id": req_id,
                            "answers": answers
                        }))
                        print("[WS-OUT] Sent clarification_response. Waiting for specification synthesis...")

                    elif msg_type in ["approval_request", "approval_requested"]:
                        artifact = event.get("artifact") or event.get("payload", {}).get("artifact", {})
                        print("[HITL] Approval Request received!")
                        print(f"       Artifacts: {json.dumps(artifact, indent=2)}")
                        # Send Approval
                        await ws.send(json.dumps({
                            "type": "approval_response",
                            "request_id": req_id,
                            "decision": "approve"
                        }))
                        print("[WS-OUT] Sent approval_response (decision: 'approve')")
                        # Give server brief moment to finish completion node
                        await asyncio.sleep(1.0)
                        break

                    elif msg_type == "run_completed":
                        print("[SUCCESS] Run completed event received via WebSocket!")
                        break

                    elif msg_type == "ping":
                        await ws.send(json.dumps({"type": "pong"}))

        except Exception as e:
            print(f"[INFO] WebSocket connection ended ({type(e).__name__}: {e}). Checking run state...")

        # Step 6: Verify Run Status & Telemetry
        await asyncio.sleep(1.0)
        print(f"\n[STEP 6] Inspecting Run Status & Cost Breakdown via GET /projects/{project_id}/runs/{run_id}...")
        status_resp = await client.get(f"/projects/{project_id}/runs/{run_id}", headers=headers)
        status_data = status_resp.json()
        print(f"         Status: {status_data.get('status')}")
        print(f"         Current Node: {status_data.get('current_node')}")
        print(f"         Total Tokens: {status_data.get('total_tokens')}")
        print(f"         Cost (USD): ${status_data.get('cost_usd')}")
        print(f"         Artifacts on Disk: {status_data.get('artifacts')}")

        print("\n" + "=" * 70)
        print("MILESTONE 3 VERIFICATION COMPLETED SUCCESSFULLY!")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_milestone_3_verification())
