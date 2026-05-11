"""
테스트용 공통 픽스처.

설계:
- 세션 단위로 테스트 DB 의 테이블을 생성하고, 종료 시 drop 합니다.
- 각 테스트는 트랜잭션 안에서 실행되며 종료 시 롤백됩니다 (DB 상태 격리).
- FastAPI 의 `get_db` 의존성을 테스트 세션으로 오버라이드합니다.

주의:
- 운영 DB 가 아닌 별도 테스트 DB (.env 의 DB_NAME + '_test') 를 사용합니다.
- 테스트 실행 전 해당 DB 가 미리 생성되어 있어야 합니다.
"""
from typing import AsyncGenerator
from urllib.parse import quote_plus

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.database import Base, get_db
import app.models  # noqa: F401  (모델 metadata 등록)
from main import app


def _build_test_database_url() -> str:
    password = quote_plus(settings.DB_PASSWORD)
    db_name = f"{settings.DB_NAME}_test"
    return (
        f"mysql+asyncmy://{settings.DB_USER}:{password}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/{db_name}"
        f"?charset=utf8mb4"
    )


TEST_DATABASE_URL = _build_test_database_url()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """각 테스트마다 트랜잭션으로 감싸고 종료 시 롤백."""
    connection = await test_engine.connect()
    transaction = await connection.begin()

    TestSessionLocal = async_sessionmaker(
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    session = TestSessionLocal()

    try:
        yield session
    finally:
        await session.close()
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture()
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """get_db 를 테스트 세션으로 오버라이드한 HTTP 클라이언트."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
