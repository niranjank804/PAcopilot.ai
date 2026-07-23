from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from src.core.config import settings
from src.core.exceptions import AuthenticationException


def verify_google_id_token(token: str) -> dict:
    """Verifies a Google-issued ID token (from the frontend's Google
    Identity Services "Sign in with Google" button) and returns its claims.

    This is the entire OAuth surface — no client secret, no server-side
    authorization-code exchange. The frontend gets a signed ID token
    directly from Google; this just checks the signature, audience
    (must match our own client ID), and expiry, exactly as Google's own
    docs recommend for this flow.
    """

    if not settings.GOOGLE_OAUTH_CLIENT_ID:
        raise AuthenticationException("Google sign-in is not configured.")

    try:
        claims = google_id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=settings.GOOGLE_OAUTH_CLIENT_ID,
        )
    except ValueError as exc:
        raise AuthenticationException("Invalid Google sign-in token.") from exc

    if not claims.get("email_verified", False):
        raise AuthenticationException("Google account email is not verified.")

    return claims
