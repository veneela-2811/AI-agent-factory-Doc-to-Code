import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_project_crud_lifecycle(client: AsyncClient, auth_headers: dict):
    # 1. Create Project
    create_resp = await client.post(
        "/projects",
        json={"name": "Alpha Project", "description": "Core test project"},
        headers=auth_headers
    )
    assert create_resp.status_code == 201
    project = create_resp.json()
    project_id = project["id"]
    assert project["name"] == "Alpha Project"
    assert project["status"] == "draft"

    # 2. Get Project
    get_resp = await client.get(f"/projects/{project_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == project_id

    # 3. List Projects
    list_resp = await client.get("/projects", headers=auth_headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 1

    # 4. Update Project
    patch_resp = await client.patch(
        f"/projects/{project_id}",
        json={"name": "Alpha Project Renamed", "status": "ready"},
        headers=auth_headers
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "Alpha Project Renamed"
    assert patch_resp.json()["status"] == "ready"

    # 5. Non-existent Project 404
    bad_resp = await client.get("/projects/non-existent-id", headers=auth_headers)
    assert bad_resp.status_code == 404
    assert bad_resp.json()["error"]["code"] == "NOT_FOUND"
