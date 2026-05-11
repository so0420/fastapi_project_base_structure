from dotenv import load_dotenv

# 환경변수 로드 (pydantic-settings 도 .env 를 읽지만, log.py 등에서
# 직접 os.getenv 를 쓰는 모듈을 위해 가장 먼저 로드)
load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import router as api_router
from app.web import router as web_router

from app.core.config import settings
from app.core.security import setup_security
from app.database import engine, get_db
from app.utils.log import logger, setup_uvicorn_logging
from app.utils.custom_exceptions import http_exception_handler, global_exception_handler


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Application startup (env={settings.ENVIRONMENT})")
    yield
    await engine.dispose()
    logger.info("Application shutdown - DB engine disposed")


# docs 노출 여부에 따라 URL 차단
docs_url = "/docs" if settings.docs_visible else None
redoc_url = "/redoc" if settings.docs_visible else None
openapi_url = "/openapi.json" if settings.docs_visible else None

app = FastAPI(
    lifespan=lifespan,
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
)

# 보안 미들웨어 + rate limiter 일괄 설정
setup_security(app)

# uvicorn, fastapi 로그를 파일 핸들러와 통합
setup_uvicorn_logging()

# Exception Handlers 등록
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

app.include_router(api_router, prefix="/api")
app.include_router(web_router)


@app.get("/hello-world")
def hello_world():
    return {"message": "Hello World!"}


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """DB 연결 상태를 확인하는 헬스체크."""
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


if __name__ == "__main__":
    import uvicorn

    # 프록시(nginx 등) 뒤에서 동작 시 X-Forwarded-For / X-Forwarded-Proto 를 신뢰하여
    # request.client.host 를 실제 클라이언트 IP 로 설정. slowapi 의 rate limit 도
    # 이 값을 사용하므로 IP 기반 제한이 정상 동작합니다.
    forwarded_allow_ips = ",".join(settings.TRUSTED_PROXIES)

    if settings.ENVIRONMENT == "production":
        logger.info("Server starting in production...")
        uvicorn.run(
            "main:app",
            host=settings.SERVER_HOST,
            port=settings.SERVER_PORT,
            log_config=None,
            proxy_headers=True,
            forwarded_allow_ips=forwarded_allow_ips,
        )
    elif settings.ENVIRONMENT == "local":
        logger.info("Server starting in local...")
        uvicorn.run(
            "main:app",
            host=settings.SERVER_HOST,
            port=settings.SERVER_PORT,
            reload=True,
            log_config=None,
            proxy_headers=True,
            forwarded_allow_ips=forwarded_allow_ips,
        )
