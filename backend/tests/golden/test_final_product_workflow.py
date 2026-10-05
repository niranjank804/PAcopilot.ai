"""The final product test (brief §30): the Claude-style workflow, then the
PA-Copilot extended workflow, end to end through the real tools, services,
API, database and permission checks — with TM1 itself faked.

The faked server is the small model of tests/unit/tm1/test_extractor.py:
cubes Sales (Region, Product; rules read Expense) and Expense (Region,
Account); process Load Sales reads Expense and writes Sales; chore Load
Sales Nightly runs it. Load Sales has just failed on a missing element.

Each step records what it saw. With GOLDEN_EVIDENCE_DIR set, the record is
written there as JSON (docs/evidence/golden/ holds the committed run).
What this proves: the workflow is complete and governed in the
application. What it does not prove: behaviour against a real TM1 server,
which tests/live/ covers when pointed at one.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from TM1py import Process

from src.ai.agents.registry import list_agents
from src.ai.tools.tm1.analysis import AnalyzeChangeImpactTool
from src.ai.tools.tm1.changes import ProposeProcessRunTool, ProposeProcessUpdateTool, ProposeRuleUpdateTool
from src.ai.tools.tm1.cubes import GetCubeTool
from src.ai.tools.tm1.development import ValidateProcessCodeTool
from src.ai.tools.tm1.diagnostics import DiagnoseProcessFailureTool, GetChangeStatusTool
from src.ai.tools.tm1.intelligence import GetPerformanceReportTool
from src.ai.tools.tm1.processes import GetProcessTool
from src.database.models.ai_conversation import AIConversation
from src.database.models.ai_usage import AIUsage
from src.database.models.audit_log import AuditLog
from src.database.models.tm1_health import TM1ProcessRun
from src.services.engineering_memory_service import engineering_memory_service
from src.tm1.metadata.history import run_extraction
from src.tm1.services import log_service
from src.tm1.service import tm1_integration_service
from tests.fixtures.factories import auth_headers, create_org_admin, create_user, grant_system_role
from tests.unit.tm1.test_extractor import fake_tm1_client, tm1_credentials_key  # noqa: F401 - fixtures

EVIDENCE: dict[str, dict] = {}


def record(step: str, **seen):
    EVIDENCE[step] = seen


async def _tool(tool, db, org_id, user_id, **kwargs):
    db.info.pop("organization_id", None)
    return json.loads(await tool.execute(db, organization_id=org_id, user_id=user_id, **kwargs))


async def _connection(db_session, org_id, user_id, name, environment):
    connection = await tm1_integration_service.create_connection(
        db_session, organization_id=org_id, created_by=user_id, name=name, address="tm1.example.com",
        port=8010, ssl=True, username="admin", password="secret",
    )
    connection.environment = environment
    connection.visibility = "organization"
    await db_session.flush()
    return connection


@pytest.mark.asyncio
async def test_claude_style_then_extended_workflow(
    client, db_session, tm1_credentials_key, fake_tm1_client, monkeypatch  # noqa: F811
):
    tm1 = fake_tm1_client
    org, admin = await create_org_admin(db_session)
    org_id, admin_id = org.id, admin.id
    headers = auth_headers(admin)
    dev = await _connection(db_session, org_id, admin_id, "Planning DEV", "dev")
    qa = await _connection(db_session, org_id, admin_id, "Planning QA", "qa")
    prod = await _connection(db_session, org_id, admin_id, "Planning PROD", "prod")
    dev_id, qa_id, prod_id = dev.id, qa.id, prod.id
    await run_extraction(db_session, dev_id, org_id, trigger="manual")
    await db_session.commit()

    # The failure TM1 recorded.
    monkeypatch.setattr(log_service, "list_process_error_logs",
                        AsyncMock(return_value=["TM1ProcessError_20261005_Load Sales.log"]))
    monkeypatch.setattr(log_service, "get_process_error_log", AsyncMock(
        return_value='Error: Data procedure line (1): "NA" : member not found in dimension Region'))
    monkeypatch.setattr(log_service, "get_message_log", AsyncMock(return_value=[]))
    tm1.processes.compile_process.return_value = []
    tm1.processes.compile.return_value = []
    tm1.processes.exists.return_value = True
    tm1.cubes.check_rules.return_value = []
    tm1.processes.execute_with_return.return_value = (True, "CompletedSuccessfully", None)
    tm1.server.get_message_log_entries.return_value = []
    # The full process as TM1 returns it, for snapshots and candidates.
    tm1.processes.get.return_value.body_as_dict = Process(
        name="Load Sales",
        datasource_type="TM1CubeView",
        datasource_data_source_name_for_server="Expense",
        data_procedure="CellPutN(1, 'Sales', 'NA');",
    ).body_as_dict

    # ---------------------------------------------------------------
    # Claude-style workflow
    # ---------------------------------------------------------------

    process = await _tool(GetProcessTool(), db_session, org_id, admin_id, connection_id=str(dev_id),
                          process_name="Load Sales")
    assert "CellPutN(1, 'Sales', 'NA')" in json.dumps(process)
    record("01_inspect_process", process=process.get("name"), datasource=process.get("datasource_type"))

    cube = await _tool(GetCubeTool(), db_session, org_id, admin_id, connection_id=str(dev_id), cube_name="Sales")
    assert cube["dimensions"] == ["Region", "Product"]
    record("02_inspect_cube_and_dimension_order", cube=cube)

    diagnosis = await _tool(DiagnoseProcessFailureTool(), db_session, org_id, admin_id,
                            connection_id=str(dev_id), process_name="Load Sales")
    assert "Sales" in diagnosis["writes_cubes"]
    assert diagnosis["error_log"]["errors"]
    record("03_identify_writer_inspect_logs_diagnose",
           writes_cubes=diagnosis["writes_cubes"], error_log=diagnosis["error_log"]["file"],
           errors=diagnosis["error_log"]["errors"][:3])

    fixed_data = "IF(DIMIX('Region', 'NA') > 0);\n  CellPutN(1, 'Sales', 'NA');\nENDIF;"
    validated = await _tool(ValidateProcessCodeTool(), db_session, org_id, admin_id,
                            connection_id=str(dev_id), process_name="Load Sales", data=fixed_data)
    record("04_generate_fix_and_compile", validated=validated)

    draft = await _tool(ProposeProcessUpdateTool(), db_session, org_id, admin_id,
                        connection_id=str(dev_id), process_name="Load Sales", create_new=False,
                        data=fixed_data)
    assert draft["status"] == "draft", draft
    change_id = draft["draft_change_id"]
    tm1.processes.update_or_create.assert_not_called()  # a draft never touches TM1
    await db_session.commit()

    detail = await client.get(f"/tm1/connections/{dev_id}/changes/{change_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    preview = detail.json()["data"]["preview"]
    record("05_diff", change_id=change_id, preview_keys=sorted(preview or {}),
           lifecycle=[s["label"] for s in detail.json()["data"]["lifecycle"]])

    applied = await client.post(f"/tm1/connections/{dev_id}/changes/{change_id}/execute",
                                json={"acknowledge_impact": True}, headers=headers)
    assert applied.status_code == 200, applied.text
    assert applied.json()["data"]["status"] == "executed"
    tm1.processes.update_or_create.assert_called()
    record("06_approve_and_save", status=applied.json()["data"]["status"])

    run_draft = await _tool(ProposeProcessRunTool(), db_session, org_id, admin_id,
                            connection_id=str(dev_id), process_name="Load Sales")
    assert run_draft["status"] == "draft", run_draft
    await db_session.commit()
    ran = await client.post(f"/tm1/connections/{dev_id}/changes/{run_draft['draft_change_id']}/execute",
                            json={"acknowledge_impact": True}, headers=headers)
    assert ran.status_code == 200, ran.text
    record("07_run", status=ran.json()["data"]["status"],
           result=ran.json()["data"].get("execution_result"))

    status = await _tool(GetChangeStatusTool(), db_session, org_id, admin_id,
                         connection_id=str(dev_id), change_id=run_draft["draft_change_id"])
    record("08_verify", status=status)

    # ---------------------------------------------------------------
    # PA-Copilot extended workflow
    # ---------------------------------------------------------------

    impact = await _tool(AnalyzeChangeImpactTool(), db_session, org_id, admin_id,
                         connection_id=str(dev_id), object_type="cube", name="Expense", change_kind="modify")
    reached = {(i["object_type"], i["name"]) for i in impact["items"]}
    assert ("process", "Load Sales") in reached
    record("09_impact_analysis", reached=sorted(f"{t}:{n}" for t, n in reached), summary=impact["summary"])

    agents = {a.name: set(a.tool_names or []) for a in list_agents()}
    assert "diagnose_process_failure" in agents["troubleshooter"]
    assert "propose_process_update" in agents["ti"]
    record("10_specialist_agents", troubleshooter_tools=len(agents["troubleshooter"]), ti_tools=len(agents["ti"]))

    db_session.info.pop("organization_id", None)
    await engineering_memory_service.create(
        db_session, organization_id=org_id, user_id=admin_id, kind="sequence",
        text="Load Rates must run before Load Sales.", source="human",
        object_type="process", object_name="Load Sales",
    )
    block = await engineering_memory_service.prompt_block(db_session, org_id, [dev_id])
    assert "Load Rates must run before Load Sales" in block
    record("11_organization_knowledge", in_prompt=True)

    graph = await client.get(f"/tm1/connections/{dev_id}/metadata/history", headers=headers)
    assert graph.status_code == 200, graph.text
    record("12_dependency_graph", extractions=len(graph.json()["data"]))

    # Security policy: the assistant is read-only on PROD, and PROD needs two people.
    with pytest.raises(Exception) as refused:
        await _tool(ProposeRuleUpdateTool(), db_session, org_id, admin_id, connection_id=str(prod_id),
                    cube_name="Sales", rules="['Total'] = N: 1;")
    record("13_security_policy", ai_on_prod=str(refused.value)[:200])

    # Deployment: promote the applied fix DEV -> QA, apply it there.
    promoted = await client.post(f"/tm1/connections/{dev_id}/changes/{change_id}/promote",
                                 json={"target_connection_id": str(qa_id)}, headers=headers)
    assert promoted.status_code == 201, promoted.text
    qa_change = promoted.json()["data"]["id"]
    on_qa = await client.post(f"/tm1/connections/{qa_id}/changes/{qa_change}/execute",
                              json={"acknowledge_impact": True}, headers=headers)
    assert on_qa.status_code == 200, on_qa.text
    package = await client.get(f"/tm1/connections/{qa_id}/changes/{qa_change}/package", headers=headers)
    assert package.status_code == 200, package.text
    record("14_change_approval_and_deployment", qa_change=qa_change, qa_status=on_qa.json()["data"]["status"],
           package_keys=sorted(package.json()["data"]))

    rolled = await client.post(f"/tm1/connections/{qa_id}/changes/{qa_change}/rollback", headers=headers)
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["data"]["status"] == "rolled_back"
    record("15_rollback", status="rolled_back")

    scan = await client.post(f"/tm1/connections/{dev_id}/health/scan", headers=headers)
    assert scan.status_code in (200, 201), scan.text
    scanned = scan.json()["data"]["scan"]
    assert isinstance(scanned["score"], int)
    record("16_model_health", score=scanned["score"], grade=scanned["grade"],
           deductions=[d.get("category") for d in scanned.get("deductions", [])])

    now = datetime.now(timezone.utc)
    # Three ordinary runs, then tonight's: four times as long, and the newest.
    for offset, seconds in ((-timedelta(days=4), 100), (-timedelta(days=3), 110), (-timedelta(days=2), 95),
                            (timedelta(minutes=5), 400)):
        db_session.add(TM1ProcessRun(
            connection_id=dev_id, organization_id=org_id, process_name="Load Sales",
            finished_at=now + offset, elapsed_seconds=seconds,
            outcome="succeeded", source="message_log",
        ))
    await db_session.flush()
    performance = await _tool(GetPerformanceReportTool(), db_session, org_id, admin_id, connection_id=str(dev_id))
    assert [r["process"] for r in performance["regressions"]] == ["Load Sales"]
    record("17_performance_analysis", regressions=performance["regressions"])

    audit = (await db_session.execute(
        select(AuditLog.action).where(AuditLog.organization_id == org_id).order_by(AuditLog.created_at)
    )).scalars().all()
    record("18_audit", actions=sorted(set(audit)))
    assert any("execute" in a for a in audit) and any("rollback" in a for a in audit)

    conversation = AIConversation(organization_id=org_id, user_id=admin_id, title="Why did Load Sales fail?")
    db_session.add(conversation)
    await db_session.flush()
    db_session.add(AIUsage(
        conversation_id=conversation.id, organization_id=org_id, user_id=admin_id, provider="anthropic",
        model="claude-sonnet-5", prompt_tokens=12_000, completion_tokens=800, total_tokens=12_800,
        estimated_cost_usd=0.048, latency_ms=4200, agent="troubleshooter", tier="balanced",
        route_reason="tool agent", fell_back=False,
    ))
    await db_session.commit()
    costs = await client.get("/monitoring/ai-costs", headers=headers)
    assert costs.status_code == 200, costs.text
    record("19_ai_cost_tracking", report_keys=sorted(costs.json()["data"]))

    # Two people on PROD: the author cannot apply their own PROD draft.
    approver = await create_user(db_session, org_id)
    await grant_system_role(db_session, approver.id, "Organization Admin")
    await db_session.commit()
    prod_draft = await client.post(
        f"/tm1/connections/{prod_id}/changes",
        json={"change_type": "update_rules", "target_name": "Sales", "new_content": {"rules": "['Total'] = N: 2;"}},
        headers=headers,
    )
    assert prod_draft.status_code == 201, prod_draft.text
    own = await client.post(f"/tm1/connections/{prod_id}/changes/{prod_draft.json()['data']['id']}/execute",
                            json={"acknowledge_impact": True}, headers=headers)
    assert own.status_code == 403, own.text
    record("13_security_policy", ai_on_prod=EVIDENCE["13_security_policy"]["ai_on_prod"],
           prod_self_approval=own.json()["error"]["message"])

    out = os.environ.get("GOLDEN_EVIDENCE_DIR")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "final_product_workflow.json").write_text(
            json.dumps(dict(sorted(EVIDENCE.items())), indent=2, default=str), encoding="utf-8"
        )
