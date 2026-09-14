import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_document_upload_and_pipeline(client: AsyncClient, auth_headers: dict):
    # Create Project first
    p_resp = await client.post(
        "/projects",
        json={"name": "Doc Ingestion Test", "description": "Testing doc upload"},
        headers=auth_headers
    )
    project_id = p_resp.json()["id"]

    # Upload Markdown Doc
    md_content = b"# Section 1: Overview\nSystem must handle agentic tasks.\n\n## Section 2: Requirements\nMust parse docs cleanly."
    files = {"file": ("test_prd.md", md_content, "text/markdown")}

    upload_resp = await client.post(
        f"/projects/{project_id}/documents",
        files=files,
        headers=auth_headers
    )
    assert upload_resp.status_code == 202
    doc_data = upload_resp.json()
    doc_id = doc_data["document_id"]
    assert doc_data["project_id"] == project_id
    assert doc_data["filename"] == "test_prd.md"

    # Idempotent upload: same content returns existing document with 200 OK
    dup_resp = await client.post(
        f"/projects/{project_id}/documents",
        files={"file": ("test_prd.md", md_content, "text/markdown")},
        headers=auth_headers
    )
    assert dup_resp.status_code == 200
    assert dup_resp.json()["document_id"] == doc_id

    # Query Status
    status_resp = await client.get(
        f"/projects/{project_id}/documents/{doc_id}",
        headers=auth_headers
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["id"] == doc_id

    # Test Invalid File Type (415)
    bad_file = {"file": ("script.exe", b"binary content", "application/octet-stream")}
    bad_resp = await client.post(
        f"/projects/{project_id}/documents",
        files=bad_file,
        headers=auth_headers
    )
    assert bad_resp.status_code == 415
    assert bad_resp.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"

    # Test Cross-Project Isolation (404 on mismatched project_id)
    isolated_resp = await client.get(
        f"/projects/other-fake-project/documents/{doc_id}",
        headers=auth_headers
    )
    assert isolated_resp.status_code == 404
