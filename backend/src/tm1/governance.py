"""Who may change which TM1 environment.

Every connection is DEV, QA or PROD. The rules, in one place:

* Applying or rolling back a change needs the deploy right of the
  connection's environment: tm1.deploy (DEV), tm1.deploy.qa (QA),
  tm1.deploy.prod (PROD). A run needs tm1.execute on top, as before.
* PROD is a two-person rule: a production change cannot be applied by the
  person who requested it (for an AI draft, the user whose conversation
  drafted it). A rollback is exempt — undoing a bad change must not wait
  for a second person.
* The AI assistant is read-only on PROD: it can read, diagnose and analyse
  impact there, but cannot draft a change or a run. Production changes are
  drafted by a person, or come from a lower environment.
* Taking a connection out of PROD needs tm1.deploy.prod: otherwise
  relabelling it DEV would be a way around every rule above.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository

ENVIRONMENTS = ("dev", "qa", "prod")

DEPLOY_PERMISSION = {
    "dev": "tm1.deploy",
    "qa": "tm1.deploy.qa",
    "prod": "tm1.deploy.prod",
}


def environment_of(connection) -> str:
    return getattr(connection, "environment", None) or "dev"


_STRICTNESS = {"dev": 0, "qa": 1, "prod": 2}


def effective_environment(change, connection) -> str:
    """The stricter of the environment the change was drafted on and the
    connection's environment now. Relabelling a connection after drafting
    (PROD to DEV, say) therefore cannot loosen the rules for that change."""

    current = environment_of(connection)
    drafted = getattr(change, "environment", None) or current
    return max(current, drafted, key=lambda env: _STRICTNESS.get(env, 0))


async def check_can_apply(
    db: AsyncSession,
    user_id: uuid.UUID,
    change,
    connection,
    *,
    action: str,
) -> None:
    """Raise unless this user may apply (`execute`) or roll back
    (`rollback`) this change on this connection's environment."""

    environment = effective_environment(change, connection)
    permission = DEPLOY_PERMISSION[environment]

    if not await auth_repository.user_has_permission(db, user_id, permission):
        raise PermissionDeniedException(
            f"Changes to a {environment.upper()} connection need the "
            f"'{permission}' permission."
        )

    if environment == "prod" and action == "execute" and change.created_by == user_id:
        raise PermissionDeniedException(
            "A production change must be approved by someone other than the "
            "person who requested it."
        )


def check_ai_may_draft(connection) -> None:
    if environment_of(connection) == "prod":
        raise PermissionDeniedException(
            f"'{connection.name}' is a PROD connection, where the assistant is "
            "read-only: it can read and analyse, but not draft changes or runs. "
            "Draft this on a DEV or QA connection, or ask a person with "
            "production rights to make the change."
        )


async def check_environment_change(
    db: AsyncSession, user_id: uuid.UUID, current: str, requested: str
) -> None:
    """Relabelling a connection is a way round its rules (QA to DEV, then
    deploy without the QA right), so it needs the deploy right of both the
    environment it leaves and the one it enters, whenever either is QA or
    PROD."""

    if current == requested:
        return
    for environment in {current, requested} - {"dev"}:
        permission = DEPLOY_PERMISSION[environment]
        if not await auth_repository.user_has_permission(db, user_id, permission):
            raise PermissionDeniedException(
                f"Moving a connection {'out of' if environment == current else 'into'} "
                f"{environment.upper()} needs the '{permission}' permission."
            )
