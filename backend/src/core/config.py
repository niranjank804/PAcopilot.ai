from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    # A trailing newline pasted into a dashboard env var field (confirmed
    # happening in practice - Render's env var UI doesn't trim it) is
    # invisible in the UI but breaks anything that uses the value verbatim:
    # an HTTP Authorization header with an embedded newline fails at the
    # request-construction level, not as a clean 401. Stripping every
    # string value before pydantic's own type coercion catches this for
    # every setting at once, including ones added later.
    @field_validator("*", mode="before")
    @classmethod
    def _strip_string_values(cls, value):
        return value.strip() if isinstance(value, str) else value

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    APP_NAME: str = "Enterprise Planning AI"
    APP_VERSION: str = "0.1.0"
    APP_DESCRIPTION: str = "Enterprise AI Platform"

    API_V1_PREFIX: str = "/api/v1"

    # Which deployment this process is. Drives the things that must differ
    # between a laptop and a public host — interactive API docs, verbose
    # error surfaces, HSTS — from one switch rather than from several
    # independently-settable booleans that can disagree.
    ENVIRONMENT: Literal["development", "staging", "production"] = "production"

    # Defaults to False so that forgetting to set it produces the safe
    # deployment, not the leaky one. `main.py` reads this rather than
    # hardcoding, so the value set in render.yaml actually takes effect.
    DEBUG: bool = False

    # Interactive docs (/docs, /redoc, /openapi.json) enumerate every route
    # and schema in the product. Off in production unless deliberately
    # switched back on.
    ENABLE_API_DOCS: bool = False

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    DATABASE_HOST: str
    DATABASE_PORT: int
    DATABASE_NAME: str
    DATABASE_USER: str
    DATABASE_PASSWORD: str

    # SQLAlchemy's defaults (5 + 10) capped the whole deployment at 15
    # concurrent DB-bound requests. An AI request occupies its slot for the
    # length of the agent's tool loop, so that ceiling was reached at ~15
    # simultaneous users. Raise both, and keep them configurable so the
    # ceiling can be matched to the database's own max_connections rather
    # than rediscovered under load.
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 20
    # Fail fast instead of queueing for 30s behind an exhausted pool: a
    # request that waits that long has already lost the user.
    DATABASE_POOL_TIMEOUT_SECONDS: float = 10.0
    # Managed Postgres (Render, RDS) drops idle connections server-side;
    # recycling under that window keeps a stale socket from surfacing as a
    # request error.
    DATABASE_POOL_RECYCLE_SECONDS: int = 1800

    # ------------------------------------------------------------------
    # JWT Authentication
    # ------------------------------------------------------------------
    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"

    # HS256 signatures are only as strong as this string. Render's
    # generateValue produces a long random value, but a hand-set key during
    # local setup can easily be short enough to brute-force offline from a
    # single captured token — which would let anyone mint an access token
    # for any user id. Fail at startup rather than serve forgeable tokens.
    @field_validator("SECRET_KEY")
    @classmethod
    def _secret_key_long_enough(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters "
                f"(got {len(value)})."
            )

        return value

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    PASSWORD_HASH_SCHEME: str = "argon2"
    CORS_ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # Interactive API docs enumerate every route and schema. Defaults to
    # DEBUG so development keeps them and production does not.
    EXPOSE_API_DOCS_OVERRIDE: bool | None = None

    @property
    def EXPOSE_API_DOCS(self) -> bool:
        if self.EXPOSE_API_DOCS_OVERRIDE is not None:
            return self.EXPOSE_API_DOCS_OVERRIDE

        return self.DEBUG

    # IP-keyed limits for unauthenticated endpoints. These are the only
    # routes reachable without a token, so they are where credential
    # stuffing and password-reset abuse land. Per window, per client IP.
    AUTH_RATE_LIMIT_WINDOW_SECONDS: float = 300.0
    AUTH_LOGIN_ATTEMPTS_PER_WINDOW: int = 10
    AUTH_REGISTER_PER_WINDOW: int = 5
    AUTH_PASSWORD_RESET_PER_WINDOW: int = 5
    AUTH_REFRESH_PER_WINDOW: int = 60

    # System role granted to a self-registered account. Without one, a new
    # user authenticates successfully and then fails every permission check
    # — "Missing permission: ai.chat" on the chat page, "knowledge.read" on
    # the knowledge base — which reads as a broken product rather than an
    # unprovisioned account.
    #
    # Analyst is the least-privileged role that can actually use the
    # product: ai.chat, knowledge.read, monitoring.view and tm1.read, with
    # no ability to write, deploy, or administer users. Set to an empty
    # string to restore the previous behaviour of granting nothing.
    DEFAULT_SIGNUP_ROLE: str = "Analyst"

    # ------------------------------------------------------------------
    # Rate limiting (src/core/rate_limit.py)
    # ------------------------------------------------------------------
    # AI limits are far tighter than the general ones: those requests cost
    # provider money and hold a database connection for a whole agent turn,
    # so they are the ones worth capping. Deliberately generous enough that
    # ordinary interactive use never sees a 429.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_WINDOW_SECONDS: float = 60.0
    RATE_LIMIT_USER_PER_WINDOW: int = 120
    RATE_LIMIT_ORG_PER_WINDOW: int = 600
    RATE_LIMIT_AI_USER_PER_WINDOW: int = 12
    RATE_LIMIT_AI_ORG_PER_WINDOW: int = 60

    # The windows above key on user and organization id, so they can only
    # guard routes that have already authenticated. The endpoints that most
    # need a limit — login, registration, password reset — are exactly the
    # ones with no user id yet, leaving credential stuffing and reset-email
    # flooding uncapped. These key on client IP instead.
    #
    # Deliberately tight: a human signing in mis-types a password a handful
    # of times, not twenty. The password-reset budget is separate and
    # tighter still, because each attempt sends mail to a third party.
    RATE_LIMIT_AUTH_IP_PER_WINDOW: int = 20
    RATE_LIMIT_PASSWORD_RESET_IP_PER_WINDOW: int = 5

    # Number of proxies in front of the app whose X-Forwarded-For entries
    # can be trusted. Render terminates TLS and appends the real client IP,
    # so 1 is correct there. Set 0 when the app is directly exposed —
    # otherwise a caller can spoof the header and dodge the limit entirely.
    TRUSTED_PROXY_COUNT: int = 1

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
    AI_DEFAULT_MODEL: str = "claude-opus-5"

    # Adaptive thinking lets the model decide how much to reason per turn.
    # It is NOT the default on the wire: a request that omits `thinking`
    # runs with no thinking at all, which is what this codebase was doing.
    # For an agent that plans multi-step TM1 work (dependency walks, TI
    # generation, rule authoring) that is the single largest quality lever
    # available, so it is on by default here.
    AI_THINKING_ENABLED: bool = True

    # "summarized" returns readable reasoning that can be shown in the UI;
    # "omitted" (the API default) still thinks and still bills the same, it
    # just returns empty thinking text.
    AI_THINKING_DISPLAY: Literal["summarized", "omitted"] = "summarized"

    # Controls reasoning depth and overall token spend. "high" is the API
    # default; "xhigh" is the recommended setting for coding and agentic
    # work, at higher cost. Lower this before lowering model quality when
    # trimming spend.
    AI_EFFORT: Literal["low", "medium", "high", "xhigh", "max"] = "high"

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

    # ------------------------------------------------------------------
    # Tenancy
    # ------------------------------------------------------------------
    # Session-level org-scoping backstop (src/database/tenancy.py) behind
    # the existing service-layer ownership checks. Off by default so this
    # can roll out gradually: the listener stays registered either way, it
    # just no-ops when this is False. See docs/AUDIT.md for the rollout plan.
    TENANCY_ENFORCEMENT_ENABLED: bool = False

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