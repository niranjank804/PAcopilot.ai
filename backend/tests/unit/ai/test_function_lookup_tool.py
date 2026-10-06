"""lookup_tm1_function: one name, a keyword, or several names in one call.

The batch form exists because a TI answer that confirmed its functions one
at a time made 28 tool calls in the live accuracy run.
"""

import json

import pytest

from src.ai.tools.tm1.functions import LookupTM1FunctionTool
from tests.fixtures.factories import create_org_admin


async def _lookup(db_session, **kwargs):
    org, admin = await create_org_admin(db_session)
    return json.loads(await LookupTM1FunctionTool().execute(
        db_session, organization_id=org.id, user_id=admin.id, **kwargs
    ))


@pytest.mark.asyncio
async def test_one_exact_name(db_session):
    result = await _lookup(db_session, query="CellPutN")
    assert result["match"]["name"] == "CellPutN"


@pytest.mark.asyncio
async def test_several_names_in_one_call(db_session):
    result = await _lookup(db_session, names=["CellPutN", "SUBST", "NoSuchFunctionXyz"])

    assert {"CellPutN", "SUBST"} <= set(result["found"])
    assert result["not_found"] == ["NoSuchFunctionXyz"]
    assert "unconfirmed" in result["note"]


@pytest.mark.asyncio
async def test_nothing_asked(db_session):
    assert "error" in await _lookup(db_session)
