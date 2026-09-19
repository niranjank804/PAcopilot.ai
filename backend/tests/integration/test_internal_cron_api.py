"""The cron endpoints: a scheduler's entry point, closed to everyone else."""

import pytest

from src.core.config import settings


@pytest.fixture
def cron_secret(monkeypatch):
    monkeypatch.setattr(settings, "CRON_SECRET", "test-cron-secret")


@pytest.mark.asyncio
async def test_cron_is_closed_when_no_secret_is_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "CRON_SECRET", None)

    response = await client.get(
        "/internal/cron/reap-executions",
        headers={"Authorization": "Bearer anything"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_cron_rejects_a_wrong_secret(client, cron_secret):
    response = await client.get(
        "/internal/cron/reap-executions",
        headers={"Authorization": "Bearer wrong"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_cron_reaps_with_the_right_secret(client, cron_secret):
    response = await client.get(
        "/internal/cron/reap-executions",
        headers={"Authorization": "Bearer test-cron-secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    # Nothing is stale in a fresh test database; the shape is the point.
    assert body["data"] == {"reaped": 0}


def test_scheduler_runs_in_process_by_default():
    # Render keeps the loop; Vercel sets SCHEDULER_ENABLED=false and uses
    # the cron above instead.
    assert settings.SCHEDULER_ENABLED is True
