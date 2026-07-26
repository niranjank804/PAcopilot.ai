"""Session-level org-scoping backstop.

Every by-ID service method already checks
`resource.organization_id != current_user.organization_id` before
returning a row (a 404, not a 403). That's real, tested protection today —
this module is a second, structural layer behind it, not a replacement:
a future endpoint that calls `repository.get_by_id()` directly, skipping
the service-layer check, would otherwise have nothing catching it.

`OrganizationScoped` is a plain marker mixin (no columns of its own) added
to a model's bases. Any model that inherits it gets every ORM-enabled
SELECT/UPDATE/DELETE against it restricted, via `with_loader_criteria`, to
whatever organization_id is stamped on the current session
(`session.info["organization_id"]`, set once per request in
`get_current_user` — see `api/dependencies/auth.py`). A session with no
organization_id stamped (scripts, seed jobs, direct unit-test sessions) is
left completely unfiltered; that's deliberate, not a gap.

Set `__tenant_nullable__ = True` on a subclass whose organization_id column
is legitimately NULLable and whose NULL rows must stay visible from every
organization's session (e.g. global/system Role rows). Models whose NULL
rows should never be visible from a live session (e.g. AuditLog rows for a
hard-deleted org) leave it at the default `False`.

Enforcement is gated by `settings.TENANCY_ENFORCEMENT_ENABLED`. The
listener stays registered either way; "off" means it no-ops before
touching the statement at all, so query behavior is byte-identical to
before this module existed. This lets the mechanism ship inert, get
verified against the full test suite with the flag forced on in staging,
and only then become the default - see docs/AUDIT.md for the rollout plan.
"""

from sqlalchemy import event, or_
from sqlalchemy.orm import Session, with_loader_criteria

from src.core.config import settings


class OrganizationScoped:
    """Marker mixin - no columns, no declarative behavior of its own.

    Combine with BaseModel: `class Foo(BaseModel, OrganizationScoped)`.
    The model must have its own `organization_id` column; this mixin only
    opts it into the session-level filter below.
    """

    __tenant_nullable__: bool = False


def _tenant_filter(execute_state) -> None:
    if not settings.TENANCY_ENFORCEMENT_ENABLED:
        return

    if not execute_state.is_orm_statement:
        return

    org_id = execute_state.session.info.get("organization_id")

    if org_id is None:
        # No tenant context on this session - background scripts, seed
        # jobs, and sessions that never went through get_current_user.
        # Leaving these unfiltered is deliberate, not a bug.
        return

    for model in OrganizationScoped.__subclasses__():
        # Built as a plain expression (not a callable) so it's evaluated
        # fresh right here, every do_orm_execute - passing a callable to
        # with_loader_criteria instead ties into SQLAlchemy's per-class
        # cache-key machinery (meant for polymorphic "adapt per queried
        # subclass" cases) and doesn't reliably re-evaluate org_id per
        # execution the way a plain expression does.
        if getattr(model, "__tenant_nullable__", False):
            criteria = or_(
                model.organization_id == org_id,
                model.organization_id.is_(None),
            )
        else:
            criteria = model.organization_id == org_id

        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(model, criteria, include_aliases=True)
        )


_registered = False


def register_tenant_listener() -> None:
    """Idempotent: safe to call more than once (e.g. re-imports in tests)."""
    global _registered

    if _registered:
        return

    event.listen(Session, "do_orm_execute", _tenant_filter)
    _registered = True
