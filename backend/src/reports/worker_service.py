import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import (
    AuthenticationException,
    ConflictException,
    NotFoundException,
    ValidationException,
)
from src.database.models.report_worker import ReportWorker
from src.repositories.report_worker_repository import report_worker_repository
from src.reports.enums import (
    WORKER_SCHEDULABLE_STATUSES,
    WorkerCapability,
    WorkerStatus,
)
from src.reports.worker_credentials import (
    enrollment_expiry,
    generate_enrollment_token,
    generate_worker_secret,
    hash_secret,
    verify_secret,
)

# What a worker may claim about itself. Anything else it sends is dropped
# rather than stored — the capability list drives job routing, so an
# unrecognised value must never reach the claim query.
_KNOWN_CAPABILITIES = {capability.value for capability in WorkerCapability}

_MAX_LAST_ERROR_CHARS = 500


class WorkerService:
    """Worker identity, enrollment, credentials, and liveness.

    Everything here is organization-scoped from the *server's* view of
    the caller. No method takes an organization id from a worker-supplied
    payload; it comes from the authenticated user (console side) or from
    the worker row the presented credential resolved to (worker side).
    """

    # ------------------------------------------------------------------
    # Console side (authenticated users)
    # ------------------------------------------------------------------

    async def register(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
        description: str | None,
    ) -> tuple[ReportWorker, str]:
        """Create a worker slot and mint its one-time enrollment token.

        Returns the raw token alongside the row. It is stored only as a
        keyed digest, so this is the single moment it can ever be read —
        the caller is responsible for showing it once and not logging it.
        """

        name = (name or "").strip()

        if not name:
            raise ValidationException("A worker name is required.")

        existing = await report_worker_repository.get_by_name(
            db, organization_id, name
        )

        if existing is not None:
            raise ConflictException(
                f"A worker named '{name}' already exists."
            )

        token = generate_enrollment_token()

        worker = ReportWorker(
            organization_id=organization_id,
            created_by=user_id,
            name=name,
            description=description,
            status=WorkerStatus.PENDING_ENROLLMENT.value,
            enrollment_token_hash=hash_secret(token),
            enrollment_expires_at=enrollment_expiry(),
            secret_version=1,
        )

        worker = await report_worker_repository.create(db, worker)

        return worker, token

    async def list_workers(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> list[ReportWorker]:

        return await report_worker_repository.list_by_organization(
            db, organization_id
        )

    async def get_worker(
        self,
        db: AsyncSession,
        worker_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> ReportWorker:

        worker = await report_worker_repository.get_by_id(db, worker_id)

        # 404 rather than 403 for a cross-tenant id, matching how the rest
        # of this codebase answers: confirming a resource exists in some
        # other organization is itself a disclosure.
        if worker is None or worker.organization_id != organization_id:
            raise NotFoundException("Worker not found.")

        return worker

    async def rotate_credential(
        self,
        db: AsyncSession,
        worker_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> tuple[ReportWorker, str]:
        """Issue a new credential and invalidate everything in flight.

        Bumping `secret_version` is what revokes already-issued tokens:
        they carry the old version and the auth dependency compares.
        """

        worker = await self.get_worker(db, worker_id, organization_id)

        if worker.status == WorkerStatus.PENDING_ENROLLMENT.value:
            raise ConflictException(
                "This worker has not completed enrollment yet. Re-issue its "
                "enrollment token instead."
            )

        secret = generate_worker_secret()

        worker.secret_hash = hash_secret(secret)
        worker.secret_version = worker.secret_version + 1
        worker.secret_rotated_at = datetime.now(UTC)

        await report_worker_repository.update(db, worker)

        return worker, secret

    async def reissue_enrollment(
        self,
        db: AsyncSession,
        worker_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> tuple[ReportWorker, str]:
        """Mint a fresh enrollment token (e.g. the first one expired).

        Also invalidates the existing credential: a worker being
        re-enrolled is being replaced, and leaving the old machine able to
        claim jobs is precisely the stale-credential problem enrollment
        exists to avoid.
        """

        worker = await self.get_worker(db, worker_id, organization_id)

        if worker.status == WorkerStatus.DISABLED.value:
            raise ConflictException(
                "Enable the worker before re-issuing an enrollment token."
            )

        token = generate_enrollment_token()

        worker.enrollment_token_hash = hash_secret(token)
        worker.enrollment_expires_at = enrollment_expiry()
        worker.secret_hash = None
        worker.secret_version = worker.secret_version + 1
        worker.status = WorkerStatus.PENDING_ENROLLMENT.value

        await report_worker_repository.update(db, worker)

        return worker, token

    async def set_enabled(
        self,
        db: AsyncSession,
        worker_id: uuid.UUID,
        organization_id: uuid.UUID,
        *,
        enabled: bool,
    ) -> ReportWorker:

        worker = await self.get_worker(db, worker_id, organization_id)

        if enabled:
            if worker.status != WorkerStatus.DISABLED.value:
                return worker

            worker.disabled_at = None
            # Back to OFFLINE, not ONLINE: the worker has to check in
            # again before the console claims it is running.
            worker.status = (
                WorkerStatus.OFFLINE.value
                if worker.secret_hash
                else WorkerStatus.PENDING_ENROLLMENT.value
            )
        else:
            worker.status = WorkerStatus.DISABLED.value
            worker.disabled_at = datetime.now(UTC)

        return await report_worker_repository.update(db, worker)

    # ------------------------------------------------------------------
    # Worker side (unauthenticated enrollment, then credential exchange)
    # ------------------------------------------------------------------

    async def enroll(
        self,
        db: AsyncSession,
        *,
        enrollment_token: str,
        host_facts: dict,
    ) -> tuple[ReportWorker, str]:
        """Spend an enrollment token for a long-lived credential.

        Single-use by construction: the token hash is cleared in the same
        transaction that writes the credential, so a replayed enrollment
        finds nothing to match. That also means an intercepted token is
        useless once the real worker has enrolled — and the resulting
        failed enrollment is visible in the audit trail.
        """

        worker = await report_worker_repository.get_by_enrollment_token_hash(
            db, hash_secret(enrollment_token)
        )

        # One message for every failure mode below: an attacker probing
        # tokens must not learn whether a token existed, expired, or
        # belonged to a disabled worker.
        invalid = AuthenticationException(
            "The enrollment token is invalid or has expired."
        )

        if worker is None:
            raise invalid

        if worker.status == WorkerStatus.DISABLED.value:
            raise invalid

        expires_at = worker.enrollment_expires_at

        if expires_at is None:
            raise invalid

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        if expires_at < datetime.now(UTC):
            raise invalid

        secret = generate_worker_secret()

        worker.secret_hash = hash_secret(secret)
        worker.enrollment_token_hash = None
        worker.enrollment_expires_at = None
        worker.enrolled_at = datetime.now(UTC)
        worker.status = WorkerStatus.ONLINE.value
        worker.last_heartbeat_at = datetime.now(UTC)

        self._apply_host_facts(worker, host_facts)

        await report_worker_repository.update(db, worker)

        return worker, secret

    async def authenticate(
        self,
        db: AsyncSession,
        *,
        worker_id: uuid.UUID,
        secret: str,
    ) -> ReportWorker:
        """Exchange the long-lived credential for a short-lived token."""

        worker = await report_worker_repository.get_by_id(db, worker_id)

        invalid = AuthenticationException("Invalid worker credentials.")

        if worker is None:
            raise invalid

        if not verify_secret(secret, worker.secret_hash):
            raise invalid

        if worker.status == WorkerStatus.DISABLED.value:
            # Distinct message: this is an administrator's deliberate act,
            # and the operator running the worker needs to know that
            # rather than chase a credential problem. It reveals nothing
            # to someone who does not already hold a valid credential.
            raise AuthenticationException("This worker has been disabled.")

        return worker

    async def resolve_token_subject(
        self,
        db: AsyncSession,
        payload: dict,
    ) -> ReportWorker:
        """Turn a decoded worker token into a live, still-authorized row.

        The token is not trusted on its own. It is a claim about identity
        that is re-checked against the database on every request, because
        the things that matter — disabled, rotated, deleted — all happen
        after a token is issued.
        """

        invalid = AuthenticationException("Invalid or expired worker token.")

        try:
            worker_id = uuid.UUID(str(payload.get("sub")))
        except (TypeError, ValueError):
            raise invalid

        worker = await report_worker_repository.get_by_id(db, worker_id)

        if worker is None:
            raise invalid

        if payload.get("sv") != worker.secret_version:
            # Credential was rotated (or re-enrolled) after this token was
            # minted.
            raise invalid

        if str(worker.organization_id) != str(payload.get("org")):
            raise invalid

        if worker.status == WorkerStatus.DISABLED.value:
            raise AuthenticationException("This worker has been disabled.")

        if worker.secret_hash is None:
            # Enrollment was reset out from under this token.
            raise invalid

        return worker

    async def heartbeat(
        self,
        db: AsyncSession,
        worker: ReportWorker,
        *,
        host_facts: dict | None = None,
        busy: bool = False,
        last_error: str | None = None,
    ) -> ReportWorker:

        worker.last_heartbeat_at = datetime.now(UTC)
        worker.status = (
            WorkerStatus.BUSY.value if busy else WorkerStatus.ONLINE.value
        )

        if last_error is not None:
            worker.last_error = last_error[:_MAX_LAST_ERROR_CHARS]

        if host_facts:
            self._apply_host_facts(worker, host_facts)

        return await report_worker_repository.update(db, worker)

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    @staticmethod
    def effective_status(worker: ReportWorker) -> WorkerStatus:
        """What the console should show, not what was last written.

        A worker that dies does not get to write OFFLINE on its way out,
        so a stored ONLINE is only meaningful next to the heartbeat clock.
        """

        stored = WorkerStatus(worker.status)

        if stored in {
            WorkerStatus.DISABLED,
            WorkerStatus.PENDING_ENROLLMENT,
            WorkerStatus.ERROR,
        }:
            return stored

        last = worker.last_heartbeat_at

        if last is None:
            return WorkerStatus.OFFLINE

        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)

        cutoff = datetime.now(UTC) - timedelta(
            seconds=settings.REPORT_WORKER_OFFLINE_AFTER_SECONDS
        )

        if last < cutoff:
            return WorkerStatus.OFFLINE

        return stored

    @staticmethod
    def is_schedulable(worker: ReportWorker) -> bool:
        return (
            WorkerStatus(worker.status) in WORKER_SCHEDULABLE_STATUSES
            and worker.secret_hash is not None
        )

    @staticmethod
    def capabilities_of(worker: ReportWorker) -> set[WorkerCapability]:
        raw = worker.capabilities or []

        return {
            WorkerCapability(value)
            for value in raw
            if value in _KNOWN_CAPABILITIES
        }

    @staticmethod
    def _apply_host_facts(worker: ReportWorker, facts: dict) -> None:
        """Copy self-reported host facts onto the row, filtered.

        These are display and routing inputs from a customer-controlled
        process, so each is length-capped and the capability list is
        intersected with the known set rather than stored verbatim.
        """

        def trimmed(key: str, limit: int) -> str | None:
            value = facts.get(key)

            if value is None:
                return None

            return str(value)[:limit]

        if (value := trimmed("version", 30)) is not None:
            worker.version = value

        if (value := trimmed("os", 100)) is not None:
            worker.os = value

        if (value := trimmed("excel_version", 50)) is not None:
            worker.excel_version = value

        if (value := trimmed("pafe_version", 50)) is not None:
            worker.pafe_version = value

        if (value := trimmed("hostname", 100)) is not None:
            worker.hostname = value

        capabilities = facts.get("capabilities")

        if isinstance(capabilities, list):
            # Items arrive either as raw strings (worker JSON) or as
            # WorkerCapability members (a pydantic model_dump that did
            # not use mode="json"). `str()` on a str-Enum member yields
            # "WorkerCapability.EXCEL", not "excel", so unwrapping .value
            # first is what stops every capability being silently
            # discarded here — which would leave the worker eligible for
            # nothing at all.
            worker.capabilities = sorted(
                {
                    value
                    for value in (
                        str(getattr(item, "value", item)) for item in capabilities
                    )
                    if value in _KNOWN_CAPABILITIES
                }
            )


worker_service = WorkerService()
