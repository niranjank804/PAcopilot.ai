"""Answer accuracy against a real TM1 server and the real model.

Each case asks PA-Copilot a question through the real orchestrator (real
model, real tools, real TM1) and checks the answer against the truth read
straight from TM1 with TM1py at run time — not through PA-Copilot's own
tools, so a tool bug cannot make a wrong answer look right. Checks are
deterministic (no model grades another model). Latency, cost, model, tier
and tool calls are recorded per question.

It costs provider money, so it runs only when asked:

    ACCURACY_EVAL=1            plus the TM1_* variables of tests/live
    ACCURACY_REPORT_DIR=<dir>  optional: where to write report.json / report.md

Written for IBM's Planning Sample; a case whose objects do not exist on the
server is skipped, not failed. The test itself fails only if the run breaks;
the score is the result.
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from evals.case import load_cases
from evals.runner import evaluate
from src.ai.orchestrator import ai_orchestrator
from src.core.config import settings
from src.database.models.ai_tool_execution import AIToolExecution
from src.database.models.ai_usage import AIUsage
from src.tm1.client.connection_manager import tm1_connection_manager
from tests.fixtures.factories import grant_system_role

pytestmark = pytest.mark.live

# Said in many ways: "does not exist", "there's no cube called", "no cube by
# that name", "found nothing", "couldn't find it".
NOT_FOUND = re.compile(
    r"\b(does not|doesn't|doesnt|did not|didn't) exist|\bnot exist|\bnot found|\bfound nothing|\bno (such )?(cube|process)\b|\b(couldn't|could not|unable to|can't|cannot) find|\bthere (is|'s) no\b|\bis not an? (cube|process)|\bisn't an? (cube|process)"
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def _has_number(answer: str, value: float) -> bool:
    """The value appears, allowing thousands separators and rounding to the
    precision written."""

    for raw in re.findall(r"-?\d[\d,]*\.?\d*", answer):
        try:
            number = float(raw.replace(",", ""))
        except ValueError:
            continue
        digits = len(raw.split(".")[1]) if "." in raw else 0
        if abs(number - value) <= max(0.5 * 10 ** -digits, 1e-9):
            return True
    return False


def _in_order(answer: str, names: list[str]) -> bool:
    text = _norm(answer)
    position = -1
    for name in names:
        found = text.find(name.lower(), position + 1)
        if found < 0:
            return False
        position = found
    return True


def _cases(tm1) -> list[dict]:
    """The questions, with their truth read from TM1 now."""

    cases: list[dict] = []
    cubes = [c for c in tm1.cubes.get_all_names() if not c.startswith("}")]
    cases.append({
        "id": "list_cubes", "agent": "developer",
        "question": "Which cubes are on this server? Leave out control cubes.",
        "truth": cubes,
        "check": lambda a: all(c.lower() in _norm(a) for c in cubes),
    })

    if "plan_BudgetPlan" in cubes:
        dims = list(tm1.cubes.get("plan_BudgetPlan").dimensions)
        cases.append({
            "id": "dimension_order", "agent": "developer",
            "question": "List the dimensions of the plan_BudgetPlan cube, in their order.",
            "truth": dims, "check": lambda a, dims=dims: _in_order(a, dims),
        })

    with_rules = [c for c in cubes if tm1.cubes.get(c).has_rules]
    cases.append({
        "id": "cubes_with_rules", "agent": "developer",
        "question": "Which cubes have rules?",
        "truth": with_rules, "check": lambda a: all(c.lower() in _norm(a) for c in with_rules),
    })

    if "plan_department" in tm1.dimensions.get_all_names():
        count = tm1.elements.get_number_of_elements("plan_department", "plan_department")
        cases.append({
            "id": "element_count", "agent": "developer",
            "question": "How many elements does the plan_department dimension have, in total?",
            "truth": count, "check": lambda a, n=count: _has_number(a, n),
        })

    if "plan_ExchangeRate" in cubes:
        value = tm1.cells.get_value("plan_ExchangeRate", "JPY,beginning,Jan-2005")
        cases.append({
            "id": "cell_value", "agent": "analyst",
            "question": "What is the value in plan_ExchangeRate for JPY, beginning, Jan-2005?",
            "truth": value, "check": lambda a, v=value: _has_number(a, v),
        })
        # ['local'] = 1 calculates every 'local' cell. (A cell a rule covers
        # but STETs, like JPY / beginning, is stored input — and TM1 11.0
        # reports its RuleDerived flag differently by query shape, so it
        # makes no fair question.)
        flag = next(iter(tm1.cells.execute_mdx(
            "SELECT {([plan_currency].[JPY],[plan_exchange_rates].[local],[plan_time].[Jan-2005])} ON 0 "
            "FROM [plan_ExchangeRate]", cell_properties=["RuleDerived"], element_unique_names=False,
        ).values()))["RuleDerived"]
        if flag:
            cases.append({
                "id": "rule_derived", "agent": "developer",
                "question": "In plan_ExchangeRate, is the cell JPY, local, Jan-2005 typed in or calculated by a rule?",
                "truth": "calculated by a rule (['local'] = 1)",
                "check": lambda a: "rule" in _norm(a)
                and not re.search(r"\b(typed in, not|not (calculated|derived|rule))\b", _norm(a)),
            })

    processes = tm1.processes.get_all_names()
    if "plan_load_budget_to_report_cube" in processes:
        code = tm1.processes.get("plan_load_budget_to_report_cube")
        written = sorted(set(re.findall(
            r"CellPut[NS]\s*\(\s*[^,]+,\s*'([^']+)'",
            code.prolog_procedure + code.metadata_procedure + code.data_procedure + code.epilog_procedure,
            re.IGNORECASE,
        )))
        if written:
            cases.append({
                "id": "process_writes", "agent": "developer",
                "question": "Which cube does the process plan_load_budget_to_report_cube write data to?",
                "truth": written, "check": lambda a, w=written: all(c.lower() in _norm(a) for c in w),
            })
    if "plan_load_budget_ascii" in processes:
        source = tm1.processes.get("plan_load_budget_ascii").datasource_type
        cases.append({
            "id": "process_datasource", "agent": "developer",
            "question": "What kind of datasource does the process plan_load_budget_ascii read from?",
            "truth": source,
            "check": lambda a: any(k in _norm(a) for k in ("ascii", "text file", "csv", "flat file", "file")),
        })

    cases.append({
        "id": "missing_cube", "agent": "developer",
        "question": "What dimensions does the cube Sales_Forecast_2031 have?",
        "truth": "does not exist",
        "check": lambda a: bool(NOT_FOUND.search(_norm(a))),
    })
    cases.append({
        "id": "missing_process", "agent": "developer",
        "question": "Show me the data tab of the process Load_Payroll_Unicorn.",
        "truth": "does not exist",
        "check": lambda a: bool(NOT_FOUND.search(_norm(a))),
    })
    return cases


async def _ask(db_session, org, user, connection, agent, question):
    started = time.monotonic()
    result = await ai_orchestrator.chat(
        db_session, organization_id=org.id, user_id=user.id, message=question,
        agent=agent, connection_id=connection.id,
    )
    latency = time.monotonic() - started
    cost = await db_session.scalar(
        select(func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0)).where(
            AIUsage.conversation_id == result.conversation_id))
    tools = (await db_session.execute(
        select(AIToolExecution.tool_name, AIToolExecution.status).where(
            AIToolExecution.conversation_id == result.conversation_id))).all()
    return result, latency, float(cost or 0), [f"{n}:{s}" for n, s in tools]


@pytest.mark.asyncio
async def test_answer_accuracy(db_session, live_connection):
    if os.environ.get("ACCURACY_EVAL") != "1":
        pytest.skip("ACCURACY_EVAL=1 not set — the accuracy run costs provider money")
    if not settings.ANTHROPIC_API_KEY:
        pytest.skip("ANTHROPIC_API_KEY not set")

    org, user, connection = live_connection
    await grant_system_role(db_session, user.id, "Organization Admin")
    tm1 = await tm1_connection_manager.get_client(connection)
    product_version = tm1.server.get_product_version()

    rows = []
    for case in _cases(tm1):
        result, latency, cost, tools = await _ask(
            db_session, org, user, connection, case["agent"], case["question"])
        rows.append({
            "id": case["id"], "agent": case["agent"], "question": case["question"],
            "truth": case["truth"], "passed": bool(case["check"](result.content)),
            "latency_s": round(latency, 1), "cost_usd": round(cost, 4), "model": result.model,
            "tools": tools, "answer": result.content[:1500],
        })

    # The existing TI generation case: functions used must exist in TM1.
    for case in load_cases(domain="ti"):
        result, latency, cost, tools = await _ask(db_session, org, user, connection, case.agent, case.prompt)
        outcomes = evaluate(case, result.content)
        rows.append({
            "id": f"ti:{case.name}", "agent": case.agent, "question": case.prompt.strip(),
            "truth": "deterministic checks in evals/cases/ti", "passed": all(o.passed for o in outcomes),
            "latency_s": round(latency, 1), "cost_usd": round(cost, 4), "model": result.model,
            "tools": tools, "answer": result.content[:1500],
            "failures": [f"{level}: {name}" for o in outcomes for level, names in o.failures_by_severity.items() for name in names][:10],
        })

    passed = sum(r["passed"] for r in rows)
    latencies = sorted(r["latency_s"] for r in rows)
    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tm1_version": product_version,
        "cases": len(rows), "passed": passed, "accuracy": round(passed / len(rows), 3),
        "median_latency_s": latencies[len(latencies) // 2],
        "max_latency_s": latencies[-1],
        "total_cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
        "models": sorted({r["model"] for r in rows}),
    }

    out = os.environ.get("ACCURACY_REPORT_DIR")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "report.json").write_text(json.dumps({"summary": summary, "cases": rows}, indent=2,
                                                          default=str), encoding="utf-8")
        lines = [
            "# Answer accuracy — live run", "",
            f"Run {summary['run_at']} against TM1 {product_version} (Planning Sample), real model, real tools.",
            "Truth read from TM1 with TM1py at run time; deterministic checks, no model grading.", "",
            f"**{passed} / {len(rows)} correct ({summary['accuracy']:.0%})** · median {summary['median_latency_s']} s, "
            f"slowest {summary['max_latency_s']} s · total ${summary['total_cost_usd']} · models: {', '.join(summary['models'])}",
            "", "| Case | Agent | Correct | Seconds | Cost $ | Tools |", "|---|---|---|---|---|---|",
        ]
        for r in rows:
            lines.append(f"| {r['id']} | {r['agent']} | {'yes' if r['passed'] else '**no**'} | {r['latency_s']} | "
                         f"{r['cost_usd']} | {', '.join(r['tools'][:6])} |")
        (Path(out) / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2))
    assert rows, "no cases ran"
