"""Model health score and performance history (phase 8)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.database.models.tm1_health import TM1ProcessRun
from src.tm1.health import performance
from src.tm1.health.score import CATEGORIES, compute, grade, run_health_scan
from tests.fixtures.factories import create_organization, create_user
from tests.unit.tm1.test_extractor import (  # noqa: F401 - fixtures
    _create_connection,
    fake_tm1_client,
    tm1_credentials_key,
)


# ------------------------------------------------------------------ score


def test_a_clean_model_scores_100_and_an_a():
    score, deductions = compute({}, {})

    assert score == 100 and grade(score) == "A"
    assert all(d["points"] == 0 for d in deductions)


def test_each_category_costs_fixed_points_up_to_its_cap():
    score, deductions = compute({"critical_rule_findings": 2, "process_issues": 4}, {})
    by_key = {d["category"]: d for d in deductions}

    assert by_key["critical_rule_findings"]["points"] == 20
    assert by_key["process_issues"]["points"] == 2
    assert score == 78 and grade(score) == "B"

    capped, deductions = compute({"critical_rule_findings": 50}, {})
    assert {d["category"]: d for d in deductions}["critical_rule_findings"]["points"] == 40
    assert capped == 60


def test_the_score_never_goes_below_zero_and_every_cap_is_documented():
    everything = {key: 1000 for key, *_ in CATEGORIES}
    score, deductions = compute(everything, {})

    assert score == 0 and grade(score) == "F"
    assert all(d["points"] == d["cap"] for d in deductions)


def test_each_deduction_names_what_cost_it():
    _, deductions = compute({"process_errors": 1}, {"process_errors": ["process Load: 1"]})

    assert {d["category"]: d for d in deductions}["process_errors"]["evidence"] == ["process Load: 1"]


# ----------------------------------------------------------- performance


def _entry(name, seconds, at, outcome="finished executing normally"):
    return {
        "TimeStamp": at.isoformat().replace("+00:00", "Z"),
        "Message": f'Process "{name}":  {outcome}, elapsed time {seconds} seconds',
    }


def test_message_log_lines_become_runs():
    now = datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)
    runs = performance.parse_runs([
        _entry("Load Sales", 42.5, now),
        {"TimeStamp": now.isoformat(), "Message": 'Process "Load Sales" executed by user "admin"'},
        _entry("Load HR", 3, now, outcome="aborted"),
    ])

    assert [(r["process_name"], r["elapsed_seconds"], r["outcome"]) for r in runs] == [
        ("Load Sales", 42.5, "succeeded"),
        ("Load HR", 3.0, "aborted"),
    ]


async def _setup(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)
    return org, connection


def _run(org, connection, name, seconds, days_ago, outcome="succeeded"):
    return TM1ProcessRun(
        connection_id=connection.id, organization_id=org.id, process_name=name,
        finished_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        elapsed_seconds=seconds, outcome=outcome, source="message_log",
    )


@pytest.mark.asyncio
async def test_a_run_far_slower_than_usual_is_a_regression(db_session, tm1_credentials_key, fake_tm1_client):
    org, connection = await _setup(db_session)
    for day, seconds in ((10, 40), (8, 44), (6, 42), (4, 41), (0, 438)):
        db_session.add(_run(org, connection, "Workforce Load", seconds, day))
    await db_session.flush()

    report = await performance.report(db_session, connection.id, org.id)

    regression = report["regressions"][0]
    assert regression["process"] == "Workforce Load"
    assert regression["usual_seconds"] == 41.5 and regression["latest_seconds"] == 438
    assert regression["increase_percent"] == 955
    assert "normally runs in 42 s" in regression["summary"] and "+955%" in regression["summary"]


@pytest.mark.asyncio
async def test_small_or_thinly_evidenced_slowdowns_are_not_regressions(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, connection = await _setup(db_session)
    # 2 s -> 9 s is 4.5x, but only 7 s longer.
    for day, seconds in ((6, 2), (4, 2), (2, 2), (0, 9)):
        db_session.add(_run(org, connection, "Tiny", seconds, day))
    # 10x slower, but only two earlier runs to compare with.
    for day, seconds in ((4, 50), (2, 50), (0, 500)):
        db_session.add(_run(org, connection, "New Load", seconds, day))
    await db_session.flush()

    report = await performance.report(db_session, connection.id, org.id)

    assert report["regressions"] == []


@pytest.mark.asyncio
async def test_recent_failures_are_counted(db_session, tm1_credentials_key, fake_tm1_client):
    org, connection = await _setup(db_session)
    db_session.add(_run(org, connection, "Load HR", 5, 1, outcome="aborted"))
    db_session.add(_run(org, connection, "Load HR", 5, 2, outcome="aborted"))
    db_session.add(_run(org, connection, "Load HR", 5, 20, outcome="aborted"))  # older than a week
    await db_session.flush()

    report = await performance.report(db_session, connection.id, org.id)

    assert report["failures_7_days"][0]["failed_runs_7_days"] == 2


@pytest.mark.asyncio
async def test_collecting_twice_does_not_duplicate_runs(db_session, tm1_credentials_key, fake_tm1_client):
    org, connection = await _setup(db_session)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    fake_tm1_client.server.get_message_log_entries.return_value = [_entry("Load Sales", 12, now)]

    first = await performance.collect_runs(db_session, fake_tm1_client, connection.id, org.id)
    second = await performance.collect_runs(db_session, fake_tm1_client, connection.id, org.id)

    assert (first, second) == (1, 0)


# ------------------------------------------------------------------- scan


@pytest.mark.asyncio
async def test_a_scan_is_scored_kept_and_explained(db_session, tm1_credentials_key, fake_tm1_client, monkeypatch):
    org, connection = await _setup(db_session)
    fake_tm1_client.server.get_message_log_entries.return_value = []

    from src.ai.tools.tm1.health import RunModelHealthCheckTool

    monkeypatch.setattr(RunModelHealthCheckTool, "_audit_rules", AsyncMock(return_value={
        "analysed": 2, "truncated": False,
        "cubes": [{"cube": "Sales", "critical": 1, "warning": 2, "findings": []}],
    }))
    monkeypatch.setattr(RunModelHealthCheckTool, "_audit_processes", AsyncMock(return_value={
        "analysed": 1, "truncated": False,
        "processes": [{"process": "Load Sales", "errors": 0, "finding_count": 3, "findings": []}],
    }))

    scan, _ = await run_health_scan(db_session, connection.id, org.id, trigger="manual")

    by_key = {d["category"]: d for d in scan.deductions}
    assert by_key["critical_rule_findings"]["evidence"] == ["cube Sales: 1"]
    # 1 critical (10) + 2 warnings (4) + 3 process findings (1.5) = 15.5 off.
    assert scan.score == 84
    assert scan.grade == "B"
    # No dependency map: unused objects are not silently counted as zero.
    assert any("no dependency map" in n for n in scan.totals["notes"])


@pytest.mark.asyncio
async def test_the_page_reads_the_latest_scan_trend_and_performance(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    from tests.fixtures.factories import auth_headers, create_org_admin

    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    connection = await _create_connection(db_session, org.id, admin.id)
    connection_id = connection.id

    response = await client.get(f"/tm1/connections/{connection_id}/health", headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["latest"] is None and data["trend"] == []
    assert "regression" in data["performance"]["rule"]


@pytest.mark.asyncio
async def test_the_daily_scan_needs_the_cron_secret(client):
    assert (await client.get("/internal/cron/model-health")).status_code == 401
