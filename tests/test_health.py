import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["sqlite_healthy"] is True
    assert data["chromadb_healthy"] is True
    assert data["filestore_healthy"] is True
