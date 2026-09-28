"""TM1 requests carried to an on-premises gateway, and its answers back.

A TM1 server inside a company network cannot be reached from the cloud:
the network's firewall refuses every inbound connection, which is what it
is for. The PA-Copilot gateway runs inside that network and connects OUT
to this backend, asking for work; this module is the other half.

    backend (TM1py)  --request-->  broker  <--poll--  gateway  -->  TM1
    backend (TM1py)  <--answer---  broker  <--post--  gateway  <--  TM1

TM1py itself is untouched. It builds one `requests` session per TM1
connection and mounts a transport adapter on it; for a connection that is
reached through a gateway, `GatewayAdapter` is mounted instead, and every
request TM1py makes — login, cubes, MDX — travels through the gateway. So
every feature that works against a directly reachable TM1 works here too.

The broker is where the two halves meet. The backend runs as short-lived
serverless instances, so the request and the gateway's poll usually land
on different machines: in production the broker is Upstash Redis (lists
for the messages, Pub/Sub to wake the waiting side instantly — the REST
API has no blocking list pop). Without Upstash it is an in-process broker,
which is exactly right for the single-process local copy and for tests.

Answers can be megabytes (a cellset); they are compressed and cut into
parts well under Upstash's request limit and Vercel's 4.5 MB body limit.
"""

import base64
import json
import logging
import threading
import time
import uuid
import zlib
from collections import defaultdict, deque

import httpx
import requests
from requests.adapters import BaseAdapter
from requests.models import Response
from requests.structures import CaseInsensitiveDict
from requests.utils import get_encoding_from_headers

from src.core.config import settings

logger = logging.getLogger(__name__)

# How long a queued request or answer lives unclaimed.
MESSAGE_TTL_SECONDS = 180
# Largest request the backend will queue (MDX bodies are small).
MAX_REQUEST_BYTES = 900_000
# Compressed bytes per answer part (base64 in JSON: about 700 KB a part).
PART_BYTES = 512 * 1024
# Default wait for an answer when TM1py gives no timeout.
DEFAULT_TIMEOUT_SECONDS = 60.0


def encode(data: bytes) -> str:
    return base64.b64encode(zlib.compress(data)).decode("ascii")


def decode(text: str) -> bytes:
    return zlib.decompress(base64.b64decode(text))


class GatewayError(requests.exceptions.ConnectionError):
    """The gateway reported a failure, or did not answer at all.

    The message is written here or by the gateway program, never taken
    from what TM1 answered, so it is safe to show the user — and it is
    the only thing that tells them what to fix on the gateway machine.
    """


# ---------------------------------------------------------------- brokers


class MemoryBroker:
    """One process: the local copy of PA-Copilot, and tests."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._requests: dict[str, deque] = defaultdict(deque)
        self._answers: dict[str, list[dict]] = defaultdict(list)

    def push_request(self, gateway_id: str, message: dict) -> None:
        with self._cond:
            self._requests[gateway_id].append(message)
            self._cond.notify_all()

    def pop_request(self, gateway_id: str, wait: float) -> dict | None:
        deadline = time.monotonic() + wait
        with self._cond:
            while not self._requests[gateway_id]:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cond.wait(remaining)
            return self._requests[gateway_id].popleft()

    def push_answer_part(self, request_id: str, part: dict) -> None:
        with self._cond:
            self._answers[request_id].append(part)
            self._cond.notify_all()

    def pop_answer(self, request_id: str, wait: float) -> list[dict]:
        deadline = time.monotonic() + wait
        with self._cond:
            while not _complete(self._answers.get(request_id)):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._answers.pop(request_id, None)
                    raise TimeoutError
                self._cond.wait(remaining)
            return self._answers.pop(request_id)


class UpstashBroker:
    """Many instances: production, through Upstash Redis over REST."""

    def __init__(self, url: str, token: str) -> None:
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._client = httpx.Client(timeout=10.0)

    def _run(self, *command: str):
        response = self._client.post(self._url, headers=self._headers, json=list(command))
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise RuntimeError(body["error"])
        return body.get("result")

    def _pipeline(self, commands: list[list[str]]) -> None:
        response = self._client.post(
            f"{self._url}/pipeline", headers=self._headers, json=commands
        )
        response.raise_for_status()

    def _wait_for(self, channel: str, wait: float, check) -> object:
        """Subscribe to `channel`, then call `check()` once subscribed and on
        every message, until it returns something or `wait` runs out.

        Checking only after the subscription is confirmed closes the race
        where the message is published between a first check and the
        subscription starting — it would otherwise be missed until timeout.
        """

        deadline = time.monotonic() + wait
        try:
            with self._client.stream(
                "POST",
                f"{self._url}/subscribe/{channel}",
                headers={**self._headers, "Accept": "text/event-stream"},
                timeout=httpx.Timeout(10.0, read=max(wait, 1.0)),
            ) as stream:
                for line in stream.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    found = check()
                    if found is not None:
                        return found
                    if time.monotonic() >= deadline:
                        return None
        except httpx.ReadTimeout:
            pass
        return check()

    def push_request(self, gateway_id: str, message: dict) -> None:
        key = f"gw:req:{gateway_id}"
        self._pipeline(
            [
                ["RPUSH", key, json.dumps(message)],
                ["EXPIRE", key, str(MESSAGE_TTL_SECONDS)],
                ["PUBLISH", f"gw:wake:{gateway_id}", "1"],
            ]
        )

    def pop_request(self, gateway_id: str, wait: float) -> dict | None:
        key = f"gw:req:{gateway_id}"

        def check():
            raw = self._run("LPOP", key)
            return json.loads(raw) if raw else None

        return check() or self._wait_for(f"gw:wake:{gateway_id}", wait, check)

    def push_answer_part(self, request_id: str, part: dict) -> None:
        key = f"gw:res:{request_id}"
        self._pipeline(
            [
                ["RPUSH", key, json.dumps(part)],
                ["EXPIRE", key, str(MESSAGE_TTL_SECONDS)],
                ["PUBLISH", f"gw:done:{request_id}", "1"],
            ]
        )

    def pop_answer(self, request_id: str, wait: float) -> list[dict]:
        key = f"gw:res:{request_id}"

        def check():
            parts = [json.loads(p) for p in (self._run("LRANGE", key, "0", "-1") or [])]
            return parts if _complete(parts) else None

        parts = self._wait_for(f"gw:done:{request_id}", wait, check)
        if parts is None:
            raise TimeoutError
        self._run("DEL", key)
        return parts


def _complete(parts: list[dict] | None) -> bool:
    return bool(parts) and len(parts) >= int(parts[0].get("parts", 1))


_broker = None
_broker_lock = threading.Lock()


def get_broker():
    global _broker
    with _broker_lock:
        if _broker is None:
            url = settings.UPSTASH_REDIS_REST_URL
            token = settings.UPSTASH_REDIS_REST_TOKEN
            _broker = UpstashBroker(url, token) if url and token else MemoryBroker()
        return _broker


def set_broker(broker) -> None:
    """For tests."""
    global _broker
    with _broker_lock:
        _broker = broker


# ------------------------------------------------------------ the request


def relay(
    gateway_id: str,
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
) -> dict:
    """Send one HTTP request through the gateway; return its answer."""

    request_id = uuid.uuid4().hex
    message = {
        "id": request_id,
        "method": method,
        "url": url,
        "headers": headers,
        "body": encode(body) if body else None,
        "timeout": timeout,
    }
    if len(json.dumps(message)) > MAX_REQUEST_BYTES:
        raise requests.exceptions.ConnectionError(
            "This TM1 request is too large to send through the gateway."
        )

    broker = get_broker()
    broker.push_request(gateway_id, message)
    try:
        # The gateway gives TM1 the same timeout and reports its own
        # failure, so a little over it is enough.
        parts = broker.pop_answer(request_id, timeout + 2.0)
    except TimeoutError:
        raise GatewayError(
            f"The gateway did not answer within {int(timeout)} seconds. "
            "Check that the PA-Copilot gateway is running inside the TM1 "
            "server's network."
        ) from None

    parts.sort(key=lambda p: int(p.get("index", 0)))
    meta = parts[0]
    if meta.get("error"):
        raise GatewayError(f"The gateway reported: {meta['error']}")

    data = "".join(p.get("data", "") for p in parts)
    body_bytes = decode(data) if data else b""
    return {
        "status": int(meta["status"]),
        "reason": meta.get("reason", ""),
        "headers": meta.get("headers") or {},
        "cookies": meta.get("cookies") or {},
        "body": body_bytes,
    }


def split_answer(request_id: str, answer: dict, body: bytes) -> list[dict]:
    """The gateway's side: an answer cut into parts for the broker. Kept
    here so both halves share one format (and one test)."""

    data = encode(body)
    chunk = PART_BYTES * 4 // 3
    pieces = [data[i : i + chunk] for i in range(0, len(data), chunk)] or [""]
    parts = []
    for index, piece in enumerate(pieces):
        part = {"id": request_id, "index": index, "parts": len(pieces), "data": piece}
        if index == 0:
            part.update(answer)
        parts.append(part)
    return parts


# ------------------------------------------------------- TM1py transport


class GatewayAdapter(BaseAdapter):
    """A `requests` transport that sends every request through a gateway.

    Cookies are kept here rather than in the session's jar: `requests`
    reads Set-Cookie from the raw socket response, which a relayed answer
    does not have, and TM1 identifies the session by its TM1SessionId
    cookie — without this every call after login would be anonymous.
    """

    def __init__(self, gateway_id: str) -> None:
        super().__init__()
        self.gateway_id = gateway_id
        self._cookies: dict[str, str] = {}
        self._lock = threading.Lock()

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        headers = dict(request.headers)
        with self._lock:
            if self._cookies:
                ours = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
                headers["Cookie"] = f"{headers['Cookie']}; {ours}" if headers.get("Cookie") else ours

        if isinstance(timeout, tuple):
            timeout = max(t for t in timeout if t is not None) if any(timeout) else None
        wait = float(timeout) if timeout else DEFAULT_TIMEOUT_SECONDS

        body = request.body
        if isinstance(body, str):
            body = body.encode("utf-8")

        answer = relay(
            self.gateway_id,
            method=request.method,
            url=request.url,
            headers=headers,
            body=body,
            timeout=wait,
        )

        with self._lock:
            self._cookies.update(answer["cookies"])

        response = Response()
        response.status_code = answer["status"]
        response.reason = answer["reason"]
        response.headers = CaseInsensitiveDict(answer["headers"])
        response._content = answer["body"]
        response.encoding = get_encoding_from_headers(response.headers)
        response.url = request.url
        response.request = request
        response.connection = self
        return response

    def close(self) -> None:
        pass


_installed = False


def install() -> None:
    """Route TM1py sessions for gateway connections through the gateway.

    TM1py mounts its transport in RestService._manage_http_adapter, after
    it has stored its kwargs and before its first request. A connection
    reached through a gateway passes `pa_gateway=<id>`; everything else
    keeps TM1py's own adapter, unchanged.
    """

    global _installed
    if _installed:
        return

    from TM1py.Services.RestService import RestService

    original = RestService._manage_http_adapter

    def manage_http_adapter(self):
        gateway_id = self._kwargs.get("pa_gateway")
        if gateway_id:
            self._s.mount(self._base_url, GatewayAdapter(str(gateway_id)))
            return
        original(self)

    RestService._manage_http_adapter = manage_http_adapter
    _installed = True
