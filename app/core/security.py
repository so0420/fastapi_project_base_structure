"""
보안 관련 미들웨어 및 rate limiter.

`setup_security(app)` 한 번 호출로 다음을 모두 적용합니다:
- TrustedHost (Host 헤더 변조 방지)
- CORS (origin 화이트리스트)
- 보안 응답 헤더 (XSS/Clickjacking/MIME sniff/HSTS/Referrer/CSP)
- 요청 바디 크기 제한
- Rate limit (slowapi)
- HTTPS 강제 리다이렉트 (옵션)

미들웨어 적용 순서 주의:
Starlette 는 `add_middleware` 가 LIFO 로 감싸므로, 마지막에 add 된 것이 가장 바깥쪽
(요청 시 가장 먼저 실행). 본 함수의 구현 순서는 의도된 실행 순서로 정렬되어 있습니다.
"""
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from app.core.config import settings


# --------- Rate limiter (전역에서 접근 가능) ---------
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT_DEFAULT] if settings.RATE_LIMIT_ENABLED else [],
    enabled=settings.RATE_LIMIT_ENABLED,
)


# --------- 보안 응답 헤더 ---------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """OWASP 권장 보안 헤더를 응답에 부착."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()",
        )

        # HSTS 와 CSP 는 운영(또는 https 강제) 환경에서만 부착
        if settings.ENVIRONMENT == "production":
            response.headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={settings.HSTS_MAX_AGE}; includeSubDomains",
            )
            # 문서 페이지가 열려있는 환경에서 CSP 를 강하게 걸면 swagger UI 가 깨지므로
            # docs 가 감춰진 운영에서만 적용.
            if not settings.docs_visible and settings.CSP_POLICY:
                response.headers.setdefault("Content-Security-Policy", settings.CSP_POLICY)

        # 서버 정보 노출 최소화
        response.headers.pop("Server", None)

        return response


# --------- 요청 바디 크기 제한 ---------
class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Content-Length 가 한도를 초과하면 413 으로 즉시 거절."""

    def __init__(self, app, max_size: int):
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_size:
                    return JSONResponse(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={
                            "detail": "Request body too large",
                            "max_size": self.max_size,
                        },
                    )
            except ValueError:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": "Invalid Content-Length header"},
                )
        return await call_next(request)


# --------- JSON 구조 제한 (파싱 DoS 방어) ---------
class JSONStructureLimitMiddleware(BaseHTTPMiddleware):
    """
    application/json 요청에 대해 파싱 전에 중첩 깊이/키 개수를 사전 검사.

    크기는 작더라도 깊이가 수만 단계인 JSON 은 파싱/검증 시
    재귀/메모리 폭주를 유발할 수 있어 사전에 차단합니다.
    """

    def __init__(self, app, max_depth: int, max_keys: int):
        super().__init__(app)
        self.max_depth = max_depth
        self.max_keys = max_keys

    async def dispatch(self, request: Request, call_next) -> Response:
        content_type = request.headers.get("content-type", "").lower()
        if not content_type.startswith("application/json"):
            return await call_next(request)

        body = await request.body()
        if not body:
            return await call_next(request)

        err = self._scan(body)
        if err is not None:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": err},
            )

        # body 를 이미 읽었으므로 다운스트림에 다시 흘려보내기 위해 receive 를 재구성
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = receive  # type: ignore[attr-defined]
        return await call_next(request)

    def _scan(self, body: bytes) -> str | None:
        """바이트 단위 스캔으로 depth, key 수를 측정. 한도 초과 시 사유 반환."""
        depth = 0
        keys = 0
        in_string = False
        escape = False
        for b in body:
            if escape:
                escape = False
                continue
            if in_string:
                if b == 0x5C:  # \
                    escape = True
                elif b == 0x22:  # "
                    in_string = False
                continue
            if b == 0x22:  # "
                in_string = True
            elif b == 0x7B or b == 0x5B:  # { or [
                depth += 1
                if depth > self.max_depth:
                    return f"JSON nesting depth exceeds {self.max_depth}"
            elif b == 0x7D or b == 0x5D:  # } or ]
                depth -= 1
            elif b == 0x3A:  # :
                keys += 1
                if keys > self.max_keys:
                    return f"JSON keys exceed {self.max_keys}"
        return None


# --------- 진입점 ---------
def setup_security(app: FastAPI) -> None:
    """모든 보안 미들웨어 및 rate limiter 를 한 번에 설정."""

    # Rate limiter 를 app.state 에 등록 (@limiter.limit 데코레이터가 참조)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # ---- inner → outer 순으로 add (실행은 역순) ----

    # 1. Rate limit (가장 안쪽: 라우트 직전)
    if settings.RATE_LIMIT_ENABLED:
        app.add_middleware(SlowAPIMiddleware)

    # 2. JSON 구조 제한 (파싱 DoS 방어)
    app.add_middleware(
        JSONStructureLimitMiddleware,
        max_depth=settings.MAX_JSON_DEPTH,
        max_keys=settings.MAX_JSON_KEYS,
    )

    # 3. 본문 크기 제한
    app.add_middleware(BodySizeLimitMiddleware, max_size=settings.MAX_REQUEST_BODY_SIZE)

    # 4. 보안 응답 헤더
    app.add_middleware(SecurityHeadersMiddleware)

    # 5. CORS (origin 이 명시된 경우에만)
    if settings.CORS_ALLOW_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ALLOW_ORIGINS,
            allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
            allow_methods=settings.CORS_ALLOW_METHODS,
            allow_headers=settings.CORS_ALLOW_HEADERS,
        )

    # 6. HTTPS 강제 (프로덕션 옵션)
    if settings.FORCE_HTTPS:
        app.add_middleware(HTTPSRedirectMiddleware)

    # 7. TrustedHost (가장 바깥: 요청 시 가장 먼저 검사)
    if settings.ALLOWED_HOSTS and settings.ALLOWED_HOSTS != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)
