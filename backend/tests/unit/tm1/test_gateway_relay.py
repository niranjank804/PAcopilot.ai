"""The gateway relay, both halves: this backend's TM1py transport and the
real gateway program (gateway/pa_gateway.py), joined by the in-process
broker, in front of a fake TM1 server."""

import importlib.util
import json
import os
import pathlib
import threading
import uuid

import pytest
import requests
from requests.structures import CaseInsensitiveDict

from src.tm1.gateway import relay
from src.tm1.gateway.relay import GatewayAdapter, MemoryBroker, set_broker

PROGRAM = pathlib.Path(__file__).resolve().parents[4] / "gateway" / "pa_gateway.py"


def load_program():
    spec = importlib.util.spec_from_file_location("pa_gateway", PROGRAM)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tm1_response(status=200, body=b"", headers=None, cookies=None):
    response = requests.Response()
    response.status_code = status
    response.reason = "OK"
    response._content = body
    response.headers = CaseInsensitiveDict(headers or {})
    for name, value in (cookies or {}).items():
        response.cookies.set(name, value)
    return response


class FakeTM1:
    """Stands in for the gateway's requests.Session to TM1."""

    def __init__(self, handler):
        self.handler = handler
        self.cookies = requests.cookies.RequestsCookieJar()
        self.seen: list[dict] = []

    def request(self, method, url, headers=None, data=None, **_):
        self.seen.append({"method": method, "url": url, "headers": dict(headers or {})})
        return self.handler(method, url, headers or {}, data)


@pytest.fixture
def broker():
    b = MemoryBroker()
    set_broker(b)
    yield b
    set_broker(None)


def serve(broker, gateway_id, tm1, allow=("tm1.corp.local:8010",)):
    """Run the gateway program's forwarding against `tm1` until stopped."""

    program = load_program()
    gateway = program.Gateway({"server": "https://unused", "key": "k", "allow": list(allow)})
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            message = broker.pop_request(gateway_id, 0.2)
            if message is None:
                continue
            answer, body = gateway.forward(message, tm1)
            for part in program.split_answer(message["id"], answer, body):
                broker.push_answer_part(message["id"], part)

    threading.Thread(target=loop, daemon=True).start()
    return stop


def session_through(gateway_id):
    session = requests.Session()
    session.mount("https://tm1.corp.local:8010", GatewayAdapter(gateway_id))
    return session


def test_answers_come_back_and_tm1s_session_cookie_is_kept(broker):
    gateway_id = uuid.uuid4().hex

    def tm1_server(method, url, headers, body):
        if url.endswith("/login"):
            return tm1_response(200, b"{}", {"Content-Type": "application/json"},
                                cookies={"TM1SessionId": "abc123"})
        # Every later call must present the session TM1 gave at login.
        assert "TM1SessionId=abc123" in headers.get("Cookie", "")
        return tm1_response(200, json.dumps({"value": ["Sales"]}).encode(),
                            {"Content-Type": "application/json"})

    tm1 = FakeTM1(tm1_server)
    stop = serve(broker, gateway_id, tm1)
    try:
        session = session_through(gateway_id)
        assert session.post("https://tm1.corp.local:8010/api/v1/login", timeout=5).status_code == 200
        cubes = session.get("https://tm1.corp.local:8010/api/v1/Cubes", timeout=5)
        assert cubes.json() == {"value": ["Sales"]}
    finally:
        stop.set()


def test_a_large_answer_travels_in_parts(broker):
    gateway_id = uuid.uuid4().hex
    big = os.urandom(3 * 1024 * 1024)  # incompressible: several parts

    stop = serve(broker, gateway_id, FakeTM1(lambda *_: tm1_response(200, big)))
    try:
        body = session_through(gateway_id).get("https://tm1.corp.local:8010/api/v1/x", timeout=5).content
        assert body == big
    finally:
        stop.set()


def test_the_gateway_refuses_a_tm1_server_it_was_not_given(broker):
    gateway_id = uuid.uuid4().hex
    tm1 = FakeTM1(lambda *_: tm1_response(200, b"secret"))
    stop = serve(broker, gateway_id, tm1, allow=("other-host:8010",))
    try:
        with pytest.raises(requests.exceptions.ConnectionError, match="allow-list"):
            session_through(gateway_id).get("https://tm1.corp.local:8010/api/v1/x", timeout=5)
        assert tm1.seen == []  # never forwarded
    finally:
        stop.set()


def test_no_gateway_running_is_a_timeout_that_says_so(broker):
    with pytest.raises(requests.exceptions.ReadTimeout, match="gateway is running"):
        relay.relay(uuid.uuid4().hex, method="GET", url="https://tm1.corp.local:8010/x",
                    headers={}, body=None, timeout=0.3)


def test_tm1py_logs_in_and_queries_through_the_gateway(broker):
    # The whole path: TM1Service built with pa_gateway, login and a real
    # TM1py call, answered by the gateway program from a fake TM1.
    from TM1py import TM1Service

    relay.install()
    gateway_id = uuid.uuid4().hex

    def tm1_server(method, url, headers, body):
        if "ProductVersion" in url:
            return tm1_response(200, b"11.8.02100.4", {"Content-Type": "text/plain"},
                                cookies={"TM1SessionId": "s1"})
        if "/Cubes" in url:
            return tm1_response(200, json.dumps({"value": [{"Name": "Sales"}, {"Name": "Headcount"}]}).encode(),
                                {"Content-Type": "application/json"})
        return tm1_response(200, b"{}", {"Content-Type": "application/json"})

    tm1 = FakeTM1(tm1_server)
    stop = serve(broker, gateway_id, tm1)
    try:
        client = TM1Service(
            address="tm1.corp.local", port=8010, ssl=True, user="admin", password="pw",
            pa_gateway=gateway_id, timeout=5,
        )
        assert client.cubes.get_all_names() == ["Sales", "Headcount"]
        # TM1 was reached only through the gateway, with basic auth at login.
        assert tm1.seen and all("tm1.corp.local:8010" in s["url"] for s in tm1.seen)
        assert any("Authorization" in s["headers"] for s in tm1.seen)
    finally:
        stop.set()


def test_the_two_halves_share_one_answer_format():
    program = load_program()
    body = b"x" * 2_000_000
    parts = program.split_answer("r1", {"status": 200}, body)
    assert parts == relay.split_answer("r1", {"status": 200}, body)
    assert relay.decode("".join(p["data"] for p in parts)) == body
