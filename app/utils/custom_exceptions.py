from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.utils.log import logger


_GENERIC_5XX_DETAIL = "Internal Server Error"


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    HTTP 예외 핸들러 (4xx, 5xx).
    - 4xx: detail 그대로 응답 (클라이언트가 알아야 할 정보)
    - 5xx: 로그에는 원본 detail 을, production 응답에는 generic 메시지로 마스킹
    """
    if exc.status_code >= 500:
        logger.error(
            f"HTTP {exc.status_code}: {request.method} {request.url.path} - {exc.detail}"
        )
        # production 에서 내부 정보(DSN, 내부 경로 등) 노출 방지
        detail = (
            _GENERIC_5XX_DETAIL
            if settings.ENVIRONMENT == "production"
            else exc.detail
        )
    else:
        detail = exc.detail

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail},
    )


async def global_exception_handler(request: Request, exc: Exception):
    """
    처리되지 않은 모든 예외를 잡아 로그를 남기고 500을 반환합니다.
    클라이언트에는 항상 generic 메시지만 노출 (스택트레이스 비공개).
    """
    logger.error(
        f"Unhandled exception: {request.method} {request.url.path}",
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": _GENERIC_5XX_DETAIL},
    )
