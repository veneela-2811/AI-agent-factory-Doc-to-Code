import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from src.storage.pattern_seed import seed_patterns_if_needed


@pytest.mark.asyncio
async def test_seed_canonical_patterns(test_db: AsyncSession, client: AsyncClient, auth_headers: dict):
    # Trigger seeding
    seeded = await seed_patterns_if_needed(test_db)
    assert seeded >= 10

    # List patterns via API
    resp = await client.get("/patterns", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 10
    names = [p["name"] for p in data["patterns"]]
    assert "ReAct" in names
    assert "Reflection" in names
    assert "Planner-Executor" in names
    assert "Router" in names
    assert "RAG" in names
    assert "Map-Reduce / Parallel Workers" in names


@pytest.mark.asyncio
async def test_pattern_crud_lifecycle(test_db: AsyncSession, client: AsyncClient, auth_headers: dict):
    # 1. Create custom pattern
    payload = {
        "name": "Custom-Guardrail-Pattern",
        "intent": "Ensures all agent inputs and outputs pass strict safety and schema checks.",
        "structure": "Input -> Guardrail Node -> Core Agent -> Output Validator -> Final Response.",
        "when_to_use": "Strict enterprise compliance and safety applications.",
        "when_not_to_use": "Internal prototype exploration.",
        "prerequisites": ["Regex validator", "Schema filter"],
        "references": ["https://example.com/guardrails"],
        "tags": ["safety", "guardrail", "validation"]
    }
    create_resp = await client.post("/patterns", json=payload, headers=auth_headers)
    assert create_resp.status_code == 201
    pattern_data = create_resp.json()
    pattern_id = pattern_data["id"]
    assert pattern_data["name"] == "Custom-Guardrail-Pattern"

    # Duplicate name should return 409
    dup_resp = await client.post("/patterns", json=payload, headers=auth_headers)
    assert dup_resp.status_code == 409

    # 2. Get Pattern by ID
    get_resp = await client.get(f"/patterns/{pattern_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == pattern_id

    # 3. Patch Pattern
    patch_resp = await client.patch(
        f"/patterns/{pattern_id}",
        json={"intent": "Updated intent for strict safety and compliance."},
        headers=auth_headers
    )
    assert patch_resp.status_code == 200
    assert "Updated intent" in patch_resp.json()["intent"]

    # 4. Filter by Tag
    tag_resp = await client.get("/patterns?tag=guardrail", headers=auth_headers)
    assert tag_resp.status_code == 200
    assert any(p["name"] == "Custom-Guardrail-Pattern" for p in tag_resp.json()["patterns"])

    # 5. Delete Pattern
    del_resp = await client.delete(f"/patterns/{pattern_id}", headers=auth_headers)
    assert del_resp.status_code == 200

    # Verify 404 after deletion
    get_after_del = await client.get(f"/patterns/{pattern_id}", headers=auth_headers)
    assert get_after_del.status_code == 404


@pytest.mark.asyncio
async def test_bulk_upload_patterns(test_db: AsyncSession, client: AsyncClient, auth_headers: dict):
    # Bulk upload JSON array
    bulk_payload = [
        {
            "name": "Batch-Pattern-1",
            "intent": "First batch pattern for concurrent evaluation.",
            "structure": "Parallel workers.",
            "when_to_use": "Batch tasks.",
            "when_not_to_use": "Serial tasks.",
            "prerequisites": [],
            "references": [],
            "tags": ["batch", "parallel"]
        },
        {
            "name": "Batch-Pattern-2",
            "intent": "Second batch pattern for streaming telemetry.",
            "structure": "Telemetry hook layer.",
            "when_to_use": "Streaming progress.",
            "when_not_to_use": "Silent jobs.",
            "prerequisites": [],
            "references": [],
            "tags": ["telemetry", "streaming"]
        }
    ]

    bulk_resp = await client.post("/patterns/bulk", json=bulk_payload, headers=auth_headers)
    assert bulk_resp.status_code == 201
    assert bulk_resp.json()["total"] >= 2

    # Bulk upload YAML file
    yaml_content = b"""
patterns:
  - name: "Yaml-Pattern-A"
    intent: "Imported from yaml file."
    structure: "Graph pipeline."
    when_to_use: "YAML driven config."
    when_not_to_use: "Hardcoded workflows."
    prerequisites: []
    references: []
    tags: ["yaml", "config"]
"""
    files = {"file": ("patterns_upload.yaml", yaml_content, "application/x-yaml")}
    file_resp = await client.post("/patterns/bulk", files=files, headers=auth_headers)
    assert file_resp.status_code == 201
    assert any(p["name"] == "Yaml-Pattern-A" for p in file_resp.json()["patterns"])


@pytest.mark.asyncio
async def test_semantic_pattern_search(test_db: AsyncSession, client: AsyncClient, auth_headers: dict):
    # Ensure seed patterns are present
    await seed_patterns_if_needed(test_db)

    # Search for tool-use and dynamic actions
    search_payload = {
        "query": "I need an agent that calls external APIs, uses tools, and reasons about observations",
        "tags": ["tool-use"],
        "top_k": 3
    }
    resp = await client.post("/patterns/search", json=search_payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_matched"] >= 1
    top_result = data["results"][0]
    assert top_result["similarity_score"] > 0.0
    assert "pattern" in top_result
    assert "name" in top_result["pattern"]
    matched_names = [r["name"] for r in data["results"]]
    assert any(n in ["ReAct", "Tool-Use"] for n in matched_names)
