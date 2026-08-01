"""Response hardening headers.

The API is called cross-origin by the Next.js frontend, so most of these
matter less here than on the HTML app — but two do carry real weight even
for a pure JSON API:

* `X-Content-Type-Options: nosniff` stops a browser from re-interpreting a
  JSON error body as HTML and executing anything reflected into it.
* `Strict-Transport-Security` prevents a downgrade on the API origin
  itself. Access and refresh tokens travel on every request; one plaintext
  round trip is enough to hand them over.

A restrictive CSP is included because FastAPI serves the docs UI and any
future HTML from this origin; it costs nothing for JSON responses.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

_BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    # No inline script or framing for anything this origin serves. The
    # JSON API needs none of these sources; the value exists to constrain
    # the docs UI and any HTML added later.
    "Content-Security-Policy": (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'none'"
    ),
}

# Two years, with subdomains, and preload-eligible. Only sent when the app
# is actually behind TLS — emitting it in local development would pin
# http://localhost to HTTPS in the developer's browser and be a nuisance
# to undo.
_HSTS = "max-age=63072000; includeSubDomains; preload"

# Swagger UI and ReDoc load their bundles from a CDN and run inline
# scripts, so `default-src 'none'` renders them blank. These paths get
# every other header but not the CSP. They only exist when
# ENABLE_API_DOCS is on, which is off in production.
_CSP_EXEMPT_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})


class SecurityHeadersMiddleware(BaseHTTPMiddleware):

    def __init__(self, app: ASGIApp, *, enable_hsts: bool = True):
        super().__init__(app)
        self._enable_hsts = enable_hsts

    async def dispatch(self, request, call_next):
        response = await call_next(request)

        exempt_from_csp = request.url.path in _CSP_EXEMPT_PATHS

        for header, value in _BASE_HEADERS.items():
            if exempt_from_csp and header == "Content-Security-Policy":
                continue

            # setdefault semantics: a route that deliberately set its own
            # CSP (e.g. to serve the docs UI) keeps it.
            response.headers.setdefault(header, value)

        if self._enable_hsts:
            response.headers.setdefault("Strict-Transport-Security", _HSTS)

        return response
