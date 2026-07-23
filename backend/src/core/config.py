from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    APP_NAME: str = "Enterprise Planning AI"
    APP_VERSION: str = "0.1.0"
    APP_DESCRIPTION: str = "Enterprise AI Platform"

    API_V1_PREFIX: str = "/api/v1"

    DEBUG: bool = True

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    DATABASE_HOST: str
    DATABASE_PORT: int
    DATABASE_NAME: str
    DATABASE_USER: str
    DATABASE_PASSWORD: str

    # ------------------------------------------------------------------
    # JWT Authentication
    # ------------------------------------------------------------------
    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    PASSWORD_HASH_SCHEME: str = "argon2"
    CORS_ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # Client ID only — not secret, meant to be exposed client-side (the
    # frontend's NEXT_PUBLIC_GOOGLE_CLIENT_ID must match). No client secret
    # is needed: the backend only verifies Google-issued ID tokens, it
    # never performs a server-side authorization-code exchange.
    GOOGLE_OAUTH_CLIENT_ID: str | None = None

    # Base URL the frontend is served from — used to build links embedded in
    # emails (e.g. the password reset link). Not the API's own URL.
    FRONTEND_URL: str = "http://localhost:3000"
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30

    # ------------------------------------------------------------------
    # Email
    # ------------------------------------------------------------------
    # Unset by default — get_email_provider() falls back to logging emails
    # to the console instead of failing to import/start, same lazy-config
    # pattern as ANTHROPIC_API_KEY/OPENAI_API_KEY above.
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_USE_TLS: bool = True
    SMTP_FROM_EMAIL: str = "no-reply@pa-copilot.local"

    # ------------------------------------------------------------------
    # AI
    # ------------------------------------------------------------------
    ANTHROPIC_API_KEY: str | None = None
    AI_DEFAULT_MODEL: str = "claude-opus-4-8"
    OPENAI_API_KEY: str | None = None
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    # Global monthly token cap applied to every organization; None = unlimited.
    # A per-organization limit needs a real billing/plan concept first.
    AI_MONTHLY_TOKEN_LIMIT: int | None = None

    # ------------------------------------------------------------------
    # TM1
    # ------------------------------------------------------------------
    TM1_CREDENTIALS_KEY: str | None = None
    TM1_REQUEST_TIMEOUT_SECONDS: float = 30.0
    TM1_MAX_RETRIES: int = 3
    TM1_CIRCUIT_BREAKER_THRESHOLD: int = 5
    TM1_CIRCUIT_BREAKER_COOLDOWN_SECONDS: float = 30.0

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
    )

    @property
    def DATABASE_URL(self):
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.DATABASE_USER,
            password=self.DATABASE_PASSWORD,
            host=self.DATABASE_HOST,
            port=self.DATABASE_PORT,
            database=self.DATABASE_NAME,
        )


settings = Settings()