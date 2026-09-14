import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_auth_login_and_access(client: AsyncClient):
    # Test Login
    resp = await client.post("/auth/login", json={"username": "admin", "password": "password123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    token = data["access_token"]

    # Test protected route with valid token
    headers = {"Authorization": f"Bearer {token}"}
    p_resp = await client.get("/projects", headers=headers)
    assert p_resp.status_code == 200

    # Test protected route without token (401)
    unauth_resp = await client.get("/projects")
    assert unauth_resp.status_code == 401
    assert unauth_resp.json()["error"]["code"] == "MISSING_TOKEN"


@pytest.mark.asyncio
async def test_invalid_token(client: AsyncClient):
    headers = {"Authorization": "Bearer invalid.jwt.token"}
    resp = await client.get("/projects", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_TOKEN"
