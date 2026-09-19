"""HTTP client for the PA-Copilot worker plane.

All traffic is outbound. The worker holds a long-lived credential and
exchanges it for a short-lived bearer token, which this client renews
automatically shortly before expiry and again on a single 401. There is
no retry loop around authentication beyond that one attempt: a
credential that is genuinely rejected must surface as an error an
operator sees, not as a process that silently retries forever against a
disabled worker.
"""

import time
from typing import Any

import requests

from pa_worker import __version__
from pa_worker.config import WorkerConfig, WorkerCredentials
from pa_worker.errors import AuthenticationError, ControlPlaneError
from pa_worker.logging import get_logger, redact

logger = get_logger("client")

# Renew this long before the token actually expires, so a slow request
# started just under the wire does not land after it.
_TOKEN_RENEW_MARGIN_SECONDS = 60

_CONNECT_TIMEOUT = 10
_READ_TIMEOUT = 120

# Statuses that mean "the edge accepted the request but the application
# never saw it" — a proxy could not reach an upstream that is booting.
# On a free-tier host that spins down after ~15 minutes idle, this is
# the normal first request after a quiet spell, not a fault.
#
# Retrying these is safe *because* the request never reached the app:
# there is no chance a job was claimed or an artifact stored and only
# the response lost. A read timeout is deliberately NOT in this set —
# there the request may well have been processed, and blindly retrying
# `claim` would take a second job while the first sat orphaned.
_COLD_START_STATUSES = frozenset({502, 503, 504})

# Roughly 2 + 4 + 8 + 16 = 30s of waiting, which covers a typical
# free-tier cold start. Bounded, so a genuinely dead server still fails
# in well under a minute rather than hanging the poll loop.
_COLD_START_ATTEMPTS = 4
_COLD_START_BACKOFF_SECONDS = 2


class ControlPlaneClient:

    def __init__(
        self,
        config: WorkerConfig,
        credentials: WorkerCredentials | None = None,
        *,
        session: requests.Session | None = None,
    ):
        self.config = config
        self.credentials = credentials
        self.base_url = config.server_url.rstrip("/")

        self._session = session or requests.Session()
        self._session.headers.update(
            {"User-Agent": f"pa-copilot-worker/{__version__}"}
        )

        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def enroll(
        self,
        enrollment_token: str,
        host_facts: dict[str, Any],
    ) -> WorkerCredentials:
        """Spend a single-use enrollment token for a credential.

        The only call that does not require a bearer token, because it is
        what establishes identity in the first place.
        """

        payload = self._request(
            "POST",
            "/worker/enroll",
            json={"enrollment_token": enrollment_token, "host": host_facts},
            authenticated=False,
        )

        credentials = WorkerCredentials(
            worker_id=payload["worker_id"],
            worker_secret=payload["worker_secret"],
            organization_id=payload["organization_id"],
            secret_version=payload.get("secret_version", 1),
        )

        self.credentials = credentials

        return credentials

    def _ensure_token(self, force: bool = False) -> str:
        if not self.credentials:
            raise AuthenticationError(
                "This worker is not enrolled. Run `pa-worker enroll` first."
            )

        if (
            not force
            and self._token
            and time.monotonic() < self._token_expires_at - _TOKEN_RENEW_MARGIN_SECONDS
        ):
            return self._token

        payload = self._request(
            "POST",
            "/worker/token",
            json={
                "worker_id": self.credentials.worker_id,
                "worker_secret": self.credentials.worker_secret,
            },
            authenticated=False,
        )

        self._token = payload["access_token"]
        self._token_expires_at = time.monotonic() + int(payload["expires_in"])

        logger.debug("Worker access token renewed")

        return self._token

    # ------------------------------------------------------------------
    # Liveness and jobs
    # ------------------------------------------------------------------

    def heartbeat(
        self,
        *,
        busy: bool = False,
        host_facts: dict[str, Any] | None = None,
        last_error: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"busy": busy}

        if host_facts is not None:
            body["host"] = host_facts

        if last_error is not None:
            body["last_error"] = redact(last_error)[:500]

        return self._request("POST", "/worker/heartbeat", json=body)

    def claim_job(self) -> dict[str, Any] | None:
        """Ask for one job. `None` means the queue had nothing for us."""

        return self._request("POST", "/worker/jobs/claim", json={})

    def download_workbook(self, execution_id: str) -> tuple[bytes, str | None]:
        """Fetch the workbook for a job, with the server's checksum.

        Returns the raw bytes and the checksum the server recorded. The
        caller verifies; this client deliberately does not, so that the
        verification failure is attributed to the execution step that
        cares about it.

        Preferred path: a signed link to the file in storage, fetched
        directly — the control plane may run where a response cannot
        exceed 4.5 MB. Older servers answer 404 to the link request and
        the workbook is streamed through the API as before.
        """

        link = self._raw_request("GET", f"/worker/jobs/{execution_id}/workbook-url")

        if link.status_code == 200:
            data = link.json().get("data") or {}

            return self._fetch_signed(data["url"]), data.get("checksum")

        if link.status_code != 404:
            self._raise_for_status(link)

        response = self._raw_request("GET", f"/worker/jobs/{execution_id}/workbook")

        return response.content, response.headers.get("X-Workbook-Checksum")

    def _fetch_signed(self, url: str) -> bytes:
        """GET a signed storage URL. No bearer token: the URL is the
        authorization, and the token belongs to the control plane only."""

        try:
            response = self._session.get(
                url,
                timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
                verify=self.config.verify_tls,
            )
        except requests.RequestException as exc:
            raise ControlPlaneError(
                f"Could not reach storage ({type(exc).__name__})."
            ) from exc

        if response.status_code != 200:
            raise ControlPlaneError(
                f"Storage refused the download (HTTP {response.status_code})."
            )

        return response.content

    def _put_signed(self, url: str, headers: dict[str, str], content: bytes) -> None:
        try:
            response = self._session.put(
                url,
                data=content,
                headers=headers,
                timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
                verify=self.config.verify_tls,
            )
        except requests.RequestException as exc:
            raise ControlPlaneError(
                f"Could not reach storage ({type(exc).__name__})."
            ) from exc

        if response.status_code not in (200, 201, 204):
            raise ControlPlaneError(
                f"Storage refused the upload (HTTP {response.status_code})."
            )

    def start_job(self, execution_id: str) -> dict[str, Any]:
        return self._request("POST", f"/worker/jobs/{execution_id}/start", json={})

    def report_progress(self, execution_id: str, step: str) -> dict[str, Any]:
        """Extend the lease and record the step reached.

        A rejection here is meaningful, not noise: it means the control
        plane no longer considers this execution ours (cancelled, timed
        out, or reaped). The caller treats that as a signal to stop and
        clean up.
        """

        return self._request(
            "POST",
            f"/worker/jobs/{execution_id}/progress",
            json={"step": step},
        )

    def upload_artifact(
        self,
        execution_id: str,
        *,
        filename: str,
        output_format: str,
        content: bytes,
        checksum: str,
        mime_type: str,
    ) -> dict[str, Any]:
        """Upload one artifact. Idempotent server-side per (job, format).

        Preferred path: put the file in storage under a signed URL and
        record it by key, so the artifact never crosses the control
        plane's body limit. Older servers answer 404 to the link request
        and receive the multipart upload as before.
        """

        link = self._raw_request(
            "POST",
            f"/worker/jobs/{execution_id}/artifacts/upload-url",
            json={
                "filename": filename,
                "content_type": mime_type,
                "size_bytes": len(content),
            },
        )

        if link.status_code == 201:
            target = link.json().get("data") or {}
            self._put_signed(target["url"], target.get("headers") or {}, content)

            return self._request(
                "POST",
                f"/worker/jobs/{execution_id}/artifacts/from-upload",
                json={
                    "key": target["key"],
                    "filename": filename,
                    "output_format": output_format,
                    "checksum": checksum,
                },
            )

        if link.status_code not in (404, 503):
            self._raise_for_status(link)

        return self._request(
            "POST",
            f"/worker/jobs/{execution_id}/artifacts",
            files={"file": (filename, content, mime_type)},
            data={"output_format": output_format, "checksum": checksum},
        )

    def complete_job(
        self,
        execution_id: str,
        *,
        trace_log: str | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/worker/jobs/{execution_id}/complete",
            json={
                "trace_log": redact(trace_log) if trace_log else None,
                "diagnostics": redact(diagnostics) if diagnostics else None,
            },
        )

    def fail_job(
        self,
        execution_id: str,
        *,
        error_code: str,
        diagnostics: dict[str, Any] | None = None,
        trace_log: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/worker/jobs/{execution_id}/fail",
            json={
                "error_code": error_code,
                "diagnostics": redact(diagnostics) if diagnostics else None,
                "trace_log": redact(trace_log) if trace_log else None,
            },
        )

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _raw_request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        **kwargs: Any,
    ) -> requests.Response:
        url = f"{self.base_url}{path}"

        headers = dict(kwargs.pop("headers", {}))

        if authenticated:
            headers["Authorization"] = f"Bearer {self._ensure_token()}"

        try:
            response = self._session.request(
                method,
                url,
                headers=headers,
                timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
                verify=self.config.verify_tls,
                **kwargs,
            )
        except requests.RequestException as exc:
            # Type only, never the exception text: a requests error can
            # embed the full URL including any query string.
            raise ControlPlaneError(
                f"Could not reach PA-Copilot ({type(exc).__name__})."
            ) from exc

        if response.status_code == 401 and authenticated:
            # Exactly one retry, with a freshly minted token. Covers the
            # ordinary case of a token that expired mid-flight; a genuine
            # credential rejection fails on the second attempt.
            headers["Authorization"] = f"Bearer {self._ensure_token(force=True)}"

            try:
                response = self._session.request(
                    method,
                    url,
                    headers=headers,
                    timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
                    verify=self.config.verify_tls,
                    **kwargs,
                )
            except requests.RequestException as exc:
                raise ControlPlaneError(
                    f"Could not reach PA-Copilot ({type(exc).__name__})."
                ) from exc

        response = self._await_cold_start(
            response, method, url, headers, kwargs
        )

        self._raise_for_status(response)

        return response

    def _await_cold_start(self, response, method, url, headers, kwargs):
        """Wait out a sleeping backend rather than failing the job.

        Without this, the first call after the host spun down surfaces
        as "Could not reach PA-Copilot" and the worker treats a perfectly
        healthy deployment as an outage.
        """

        for attempt in range(_COLD_START_ATTEMPTS):
            if response.status_code not in _COLD_START_STATUSES:
                return response

            delay = _COLD_START_BACKOFF_SECONDS * (2**attempt)

            logger.info(
                f"PA-Copilot is starting up (HTTP {response.status_code}); "
                f"retrying in {delay}s"
            )

            time.sleep(delay)

            try:
                response = self._session.request(
                    method,
                    url,
                    headers=headers,
                    timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
                    verify=self.config.verify_tls,
                    **kwargs,
                )
            except requests.RequestException as exc:
                raise ControlPlaneError(
                    f"Could not reach PA-Copilot ({type(exc).__name__})."
                ) from exc

        return response

    def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        **kwargs: Any,
    ) -> Any:
        response = self._raw_request(
            method, path, authenticated=authenticated, **kwargs
        )

        if not response.content:
            return None

        try:
            body = response.json()
        except ValueError:
            raise ControlPlaneError(
                "PA-Copilot returned a response that was not JSON."
            )

        # The whole API uses the ApiResponse envelope.
        if isinstance(body, dict) and "success" in body:
            if not body.get("success"):
                error = body.get("error") or {}

                raise ControlPlaneError(
                    f"{error.get('code', 'ERROR')}: "
                    f"{redact(error.get('message', 'Unknown error'))}"
                )

            return body.get("data")

        return body

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if response.status_code < 400:
            return

        code = "ERROR"
        message = f"HTTP {response.status_code}"

        try:
            body = response.json()
            error = (body or {}).get("error") or {}
            code = error.get("code", code)
            message = error.get("message", message)
        except ValueError:
            pass

        message = redact(message)

        if response.status_code in (401, 403):
            raise AuthenticationError(
                f"{code}: {message}", status_code=response.status_code
            )

        raise ControlPlaneError(
            f"{code}: {message}", status_code=response.status_code
        )
