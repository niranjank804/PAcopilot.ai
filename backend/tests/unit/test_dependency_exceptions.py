"""Guards for security exceptions granted in CI.

An ignored vulnerability is only safe while the reason for ignoring it
holds. These tests fail when the reason stops being true, so the
exception cannot quietly outlive its justification.
"""

from src.core.config import settings

# Symmetric algorithms — HMAC over a shared secret, no elliptic curve.
_HMAC_ALGORITHMS = {"HS256", "HS384", "HS512"}


def test_jwt_algorithm_is_hmac_not_elliptic_curve():
    """Justifies ignoring PYSEC-2026-1325 in .github/workflows/security.yml.

    The advisory is a timing attack against ecdsa's P-256 signing, reached
    through python-jose. It has no fix release. It does not affect this
    application because JWTs are signed with HMAC, which never calls into
    ecdsa.

    If this assertion fails, the CI exception is no longer justified:
    either revert the algorithm change or remove the --ignore-vuln flag
    and deal with the advisory properly.
    """

    assert settings.JWT_ALGORITHM in _HMAC_ALGORITHMS, (
        f"JWT_ALGORITHM is {settings.JWT_ALGORITHM!r}. The pip-audit "
        "exception for PYSEC-2026-1325 assumes HMAC signing and is no "
        "longer valid — see .github/workflows/security.yml."
    )
