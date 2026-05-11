from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.utils.log import logger


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    HTTP 예외 핸들러 (4xx, 5xx).
    500 이상은 에러 로그를 남깁니다.
    """
    if exc.status_code >= 500:
        logger.error(
            f"HTTP {exc.status_code}: {request.method} {request.url.path} - {exc.detail}"
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


async def global_exception_handler(request: Request, exc: Exception):
    """
    처리되지 않은 모든 예외를 잡아 로그를 남기고 500을 반환합니다.
    FastAPI 라우트 핸들러 내 비동기 예외도 여기서 처리됩니다.
    """
    logger.error(
        f"Unhandled exception: {request.method} {request.url.path}",
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
    )
