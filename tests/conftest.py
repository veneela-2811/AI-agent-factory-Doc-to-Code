import os
import pytest
import pytest_asyncio
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.storage.database import Base, get_db
import src.storage.database as db_module
from src.auth.jwt import create_access_token
from src.main import app

TEST_DB_PATH = Path("./data/test_app.db")
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH.resolve()}"


@pytest_asyncio.fixture(scope="function", autouse=True)
async def test_db():
    if TEST_DB_PATH.exists():
        try:
            TEST_DB_PATH.unlink()
        except Exception:
            pass

    test_engine = create_async_engine(TEST_DB_URL, echo=False)
    test_session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    
    orig_engine = db_module.engine
    orig_session_factory = db_module.AsyncSessionLocal

    db_module.engine = test_engine
    db_module.AsyncSessionLocal = test_session_factory

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async with test_session_factory() as session:
        yield session

    db_module.engine = orig_engine
    db_module.AsyncSessionLocal = orig_session_factory
    await test_engine.dispose()
    if TEST_DB_PATH.exists():
        try:
            TEST_DB_PATH.unlink()
        except Exception:
            pass


@pytest_asyncio.fixture(scope="function")
async def client(test_db: AsyncSession):
    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    token = create_access_token({"sub": "test_engineer"})
    return {"Authorization": f"Bearer {token}"}
