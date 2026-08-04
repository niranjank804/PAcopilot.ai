from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.router import api_router
from src.core.config import settings
from src.core.exceptions import AppException
from src.core.logging import app_logger

app = FastAPI(
    title=settings.APP_NAME,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
    # Was hardcoded True, so production served debug tracebacks regardless
    # of configuration.
    debug=settings.DEBUG,
    # The interactive docs enumerate every route, parameter and schema —
    # a map of the attack surface, served to anyone. Available in
    # development, off in production. Set EXPOSE_API_DOCS=true to override
    # (behind a network restriction, not on the open internet).
    docs_url="/docs" if settings.EXPOSE_API_DOCS else None,
    redoc_url="/redoc" if settings.EXPOSE_API_DOCS else None,
    openapi_url="/openapi.json" if settings.EXPOSE_API_DOCS else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    # A 429 without Retry-After tells a client it was throttled but not for
    # how long, so the usual response is to retry immediately and be
    # throttled again.
    retry_after = getattr(exc, "retry_after", None)
    headers = (
        {"Retry-After": str(int(retry_after) + 1)}
        if retry_after is not None
        else None
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
            },
        },
        headers=headers,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": "HTTP_ERROR",
                "message": str(exc.detail),
            },
        },
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": str(exc.errors()),
            },
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    app_logger.error(f"Unhandled exception: {exc!r}")

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
            },
        },
    )


app_logger.info(f"{settings.APP_NAME} started successfully")