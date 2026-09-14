"""
1-Click End-to-End BRD Ingestion & Requirements Generation Demo
"""
import sys
import json
import asyncio
import httpx

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_URL = "http://127.0.0.1:8000"


async def main():
    print("=" * 70)
    print("🚀 RUNNING END-TO-END BRD -> WORKFLOW 1 DEMO")
    print("=" * 70)

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Login
        print("\n[1] Authenticating...")
        auth = (await client.post("/auth/login", json={"username": "dev_user", "password": "dev_password"})).json()
        token = auth["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print(f"    Authenticated. Token: {token[:20]}...")

        # 2. Create Project
        print("\n[2] Creating Project...")
        proj = (await client.post("/projects", json={"name": "OmniBot E-Commerce", "description": "BRD Requirements"}, headers=headers)).json()
        project_id = proj["id"]
        print(f"    Created Project ID: {project_id}")

        # 3. Upload BRD Document
        print("\n[3] Uploading data/samples/sample_ecommerce_agent_brd.md...")
        with open("data/samples/sample_ecommerce_agent_brd.md", "rb") as f:
            doc_res = (await client.post(
                f"/projects/{project_id}/documents",
                files={"file": ("sample_ecommerce_agent_brd.md", f, "text/markdown")},
                data={"kind": "BRD"},
                headers=headers
            )).json()
        doc_id = doc_res["document_id"]
        print(f"    Uploaded Document ID: {doc_id}")

        # Poll until document is parsed
        print("    Waiting for document parsing and ChromaDB embedding...")
        for _ in range(20):
            d_status = (await client.get(f"/projects/{project_id}/documents/{doc_id}", headers=headers)).json()
            if d_status.get("status") == "ready":
                print(f"    Document Ready! Extracted Sections: {d_status.get('total_sections')}")
                break
            await asyncio.sleep(0.5)

        # 4. Trigger Workflow 1
        print("\n[4] Triggering Workflow 1 (Requirements Gathering)...")
        wf_res = (await client.post(
            f"/projects/{project_id}/workflows/requirements",
            json={"document_ids": [doc_id]},
            headers=headers
        )).json()
        run_id = wf_res["run_id"]
        print(f"    Triggered Run ID: {run_id}")

        # 5. Handle Clarification Interrupt
        print("\n[5] Waiting for Reflection Gap Analysis & Clarification Interrupt...")
        for _ in range(10):
            r_stat = (await client.get(f"/projects/{project_id}/runs/{run_id}", headers=headers)).json()
            if r_stat.get("current_node") == "clarification_interrupt":
                print(f"    Run paused at {r_stat.get('current_node')}.")
                break
            await asyncio.sleep(0.5)

        print("    Submitting clarification answers...")
        await client.post(
            f"/projects/{project_id}/runs/{run_id}/clarifications",
            json={"answers": [{"id": "q1", "answer": "FastAPI backend with SQLite and ChromaDB"}]},
            headers=headers
        )
        print("    Clarifications submitted.")

        # 6. Wait for Synthesis and Approval Gate
        print("\n[6] Synthesizing requirements specification...")
        for _ in range(10):
            r_stat = (await client.get(f"/projects/{project_id}/runs/{run_id}", headers=headers)).json()
            if "requirements.json" in r_stat.get("artifacts", []):
                print(f"    Specification synthesized! Artifacts on disk: {r_stat.get('artifacts')}")
                break
            await asyncio.sleep(0.5)

        print("    Approving specification...")
        await client.post(f"/projects/{project_id}/runs/{run_id}/approve", headers=headers)
        print("    Approved successfully.")

        # 7. Download and display requirements.json
        print("\n[7] Fetching generated requirements.json:")
        print("=" * 70)
        req_json = (await client.get(f"/projects/{project_id}/runs/{run_id}/artifacts/requirements.json", headers=headers)).json()
        print(json.dumps(req_json, indent=2))
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
