import json
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_csv_or_json_list(v):
    """env 에 ["a","b"] (JSON) 또는 a,b (CSV) 둘 다 허용."""
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return []
        if v.startswith("["):
            return json.loads(v)
        return [s.strip() for s in v.split(",") if s.strip()]
    return v


class Settings(BaseSettings):
    """애플리케이션 전체 설정. .env 파일에서 값을 읽어옵니다."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Environment
    ENVIRONMENT: Literal["local", "staging", "production"] = "production"

    # Server
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8000

    # Log
    LOG_FILE_PATH: str = "app/logs/"

    # Database (MariaDB)
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "app"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 3600

    # ---- Security ----
    # API 문서 노출 여부. None 이면 ENVIRONMENT 기반으로 자동 결정 (production 에서만 차단).
    DOCS_ENABLED: bool | None = None

    # CORS: 허용 origin 목록. 예: ["https://app.example.com"]
    CORS_ALLOW_ORIGINS: list[str] = Field(default_factory=list)
    CORS_ALLOW_CREDENTIALS: bool = False
    CORS_ALLOW_METHODS: list[str] = Field(default_factory=lambda: ["*"])
    CORS_ALLOW_HEADERS: list[str] = Field(default_factory=lambda: ["*"])

    # Host 헤더 화이트리스트. ["*"] 는 전체 허용 (운영에서는 도메인 명시 권장).
    ALLOWED_HOSTS: list[str] = Field(default_factory=lambda: ["*"])

    # X-Forwarded-* 헤더를 신뢰할 프록시 IP 목록 (uvicorn forwarded_allow_ips).
    # 여기 등록된 IP/CIDR 에서 온 요청에만 헤더를 신뢰하여 실제 클라이언트 IP 를 인식.
    # 같은 호스트의 nginx 라면 "127.0.0.1" 로 충분. 다른 서버의 nginx 면 그 서버 IP.
    # "*" 는 모든 IP 신뢰 — 보안상 권장하지 않음.
    TRUSTED_PROXIES: list[str] = Field(default_factory=lambda: ["127.0.0.1"])

    # 요청 바디 최대 크기 (bytes). 기본 10MB.
    MAX_REQUEST_BODY_SIZE: int = 10 * 1024 * 1024

    # JSON 파싱 DoS 방어 (application/json 요청 한정)
    MAX_JSON_DEPTH: int = 20
    MAX_JSON_KEYS: int = 1000

    # Rate limit
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "100/minute"

    # HTTPS 강제 리다이렉트 (프록시/LB 없이 직접 서빙할 때만 의미 있음)
    FORCE_HTTPS: bool = False

    # 보안 헤더 옵션
    HSTS_MAX_AGE: int = 31536000  # 1년
    CSP_POLICY: str = "default-src 'self'"

    @field_validator(
        "CORS_ALLOW_ORIGINS",
        "CORS_ALLOW_METHODS",
        "CORS_ALLOW_HEADERS",
        "ALLOWED_HOSTS",
        "TRUSTED_PROXIES",
        mode="before",
    )
    @classmethod
    def _normalize_list(cls, v):
        return _parse_csv_or_json_list(v)

    @computed_field  # type: ignore[misc]
    @property
    def database_url(self) -> str:
        password = quote_plus(self.DB_PASSWORD)
        return (
            f"mysql+asyncmy://{self.DB_USER}:{password}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            f"?charset=utf8mb4"
        )

    @computed_field  # type: ignore[misc]
    @property
    def docs_visible(self) -> bool:
        """Swagger/Redoc/openapi.json 노출 여부."""
        if self.DOCS_ENABLED is not None:
            return self.DOCS_ENABLED
        return self.ENVIRONMENT != "production"


settings = Settings()
