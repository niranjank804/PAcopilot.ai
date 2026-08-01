"""The readiness probe must actually fail when a dependency is down.

The previous /health returned "healthy" unconditionally, so a deploy with
an unreachable database still passed its health check and received
traffic. These tests exist so that cannot silently return.
"""

import pytest
from sqlalchemy.exc import OperationalError

import src.api.v1.health as health_module


@pytest.mark.asyncio
async def test_liveness_is_dependency_free(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_readiness_reports_ok_when_the_database_answers(client):
    response = await client.get("/health/ready")

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "ready"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["db_pool"]["capacity"] > 0


@pytest.mark.asyncio
async def test_readiness_fails_when_the_database_is_unreachable(
    client, monkeypatch
):
    class DeadEngine:
        # Only the attributes readiness() touches.
        pool = health_module.engine.pool

        def connect(self):
            raise OperationalError("SELECT 1", {}, Exception("no route to host"))

    monkeypatch.setattr(health_module, "engine", DeadEngine())

    response = await client.get("/health/ready")

    assert response.status_code == 503

    body = response.json()

    assert body["status"] == "not_ready"
    assert body["checks"]["database"]["status"] == "error"
    # The driver message can carry the host and user from the connection
    # string, so only the exception type is exposed.
    assert "no route to host" not in response.text


@pytest.mark.asyncio
async def test_saturated_pool_is_reported_but_stays_ready(client, monkeypatch):
    class SaturatedPool:
        _max_overflow = 0

        def size(self):
            return 4

        def checkedout(self):
            return 4

    # Bound before patching: resolving health_module.engine inside connect()
    # would find this fake and recurse.
    real_engine = health_module.engine

    class SaturatedEngine:
        pool = SaturatedPool()

        def connect(self):
            return real_engine.connect()

    monkeypatch.setattr(health_module, "engine", SaturatedEngine())

    response = await client.get("/health/ready")

    # Reported, but still ready: pulling a saturated instance out of
    # rotation would push its load onto the others and cascade.
    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "ready"
    assert body["checks"]["db_pool"]["status"] == "saturated"
