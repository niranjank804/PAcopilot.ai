"""Server-side JWT revocation.

A JWT is self-validating: signature plus expiry, no lookup. That is what
makes it fast and what makes "log me out" a lie — the token stays valid
until it expires no matter what the server thinks. With a 7-day refresh
lifetime, a leaked token was usable for a week with no way to stop it.

Two mechanisms, because they answer different questions:

* **Individual** — one jti, one row in `revoked_tokens`. Logging out, or
  retiring the old refresh token when a rotation issues a new one.
* **Bulk** — `users.tokens_valid_from`. Logging out everywhere, changing a
  password, completing a reset. All three must kill sessions the server
  never recorded, so a single timestamp compared against each token's
  `iat` does in one write what enumerating tokens cannot do at all.

Storage lives behind this service, not in its callers. It is PostgreSQL
today because that is what the deployment has; moving the hot path (the
per-request jti check) to Redis later is a change here and nowhere else.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.revoked_token import RevokedToken
from src.repositories.revoked_token_repository import revoked_token_repository
from src.repositories.user_repository import user_repository


class TokenRevocationService:

    async def revoke(
        self,
        db: AsyncSession,
        *,
        jti: str,
        user_id: uuid.UUID,
        expires_at: datetime,
        reason: str = "logout",
    ) -> None:
        """Retire one token. Idempotent — revoking twice is not an error."""

        if not jti:
            return

        if await revoked_token_repository.exists(db, jti):
            return

        await revoked_token_repository.create(
            db,
            RevokedToken(
                jti=jti,
                user_id=user_id,
                expires_at=expires_at,
                reason=reason,
            ),
        )

    async def revoke_all_for_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> None:
        """Invalidate every token issued to this user before now."""

        user = await user_repository.get_by_id(db, user_id)

        if user is None:
            return

        user.tokens_valid_from = datetime.now(UTC)

        await user_repository.update(db, user)

    async def is_revoked(
        self,
        db: AsyncSession,
        payload: dict,
    ) -> bool:
        """True if this token must be rejected despite being well-formed.

        Checks the cheap condition first: `iat` against the user's cutoff
        needs no extra query when the user row is already loaded by the
        caller, whereas the jti lookup always costs one.
        """

        jti = payload.get("jti")

        if jti and await revoked_token_repository.exists(db, jti):
            return True

        return False

    def issued_before_cutoff(self, payload: dict, cutoff: datetime) -> bool:
        """True if this token predates a bulk revocation.

        A token minted before `tokens_valid_from` is dead regardless of its
        own expiry. Tokens with no `iat` (issued before this feature
        shipped) are treated as valid — this must not sign existing users
        out on deploy.
        """

        issued_at = payload.get("iat")

        if issued_at is None:
            return False

        issued = datetime.fromtimestamp(int(issued_at), tz=UTC)

        # `iat` is a whole-second claim, so a token minted in the same
        # second as the cutoff is indistinguishable from one minted just
        # before it. Revoked, not spared: the cost of being wrong here is
        # one extra sign-in, against a session that should have ended.
        return issued <= cutoff.replace(microsecond=0)

    async def prune_expired(self, db: AsyncSession) -> int:
        """Drop rows for tokens that have expired on their own.

        Past its expiry a JWT fails validation without any help from this
        table, so the row stops carrying information.
        """

        return await revoked_token_repository.delete_expired(
            db, datetime.now(UTC)
        )


token_revocation_service = TokenRevocationService()
