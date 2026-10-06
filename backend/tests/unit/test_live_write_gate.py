"""The live write gate: every condition must hold, or nothing is written.

Pure logic from tests/live/conftest.py, tested without any server."""

from tests.live.conftest import authorize_write

CFG = {"address": "localhost", "port": 12354}
INVENTORY = [{"address": "localhost", "port": 12354, "server_name": "Planning Sample", "purpose": "DEV sample"}]
ENV = {"TM1_LIVE_WRITE": "1", "TM1_LIVE_WRITE_SERVER": "Planning Sample", "LIVE_WRITE_SCOPE_CONFIRMED": "1"}


def test_all_conditions_met():
    assert authorize_write(ENV, "Planning Sample", CFG, INVENTORY) == (True, "DEV sample")


def test_each_missing_condition_blocks():
    cases = [
        ({**ENV, "TM1_LIVE_WRITE": "0"}, "Planning Sample", CFG, INVENTORY, "not authorized"),
        ({k: v for k, v in ENV.items() if k != "TM1_LIVE_WRITE_SERVER"}, "Planning Sample", CFG, INVENTORY, "not typed"),
        ({**ENV, "LIVE_WRITE_SCOPE_CONFIRMED": ""}, "Planning Sample", CFG, INVENTORY, "scope"),
        (ENV, "Production Plan", CFG, INVENTORY, "does not match"),
        (ENV, "Planning Sample", CFG, None, "no operator inventory"),
        (ENV, "Planning Sample", {"address": "tm1-prod.corp", "port": 12354}, INVENTORY, "not in the operator"),
        (ENV, "Planning Sample", {"address": "localhost", "port": 8010}, INVENTORY, "not in the operator"),
    ]
    for env, reported, cfg, inventory, why in cases:
        ok, detail = authorize_write(env, reported, cfg, inventory)
        assert not ok and why in detail, (why, detail)


def test_a_typed_name_alone_is_not_enough():
    # The typed name matches the server, but nobody approved this target.
    other = [{"address": "localhost", "port": 12354, "server_name": "Another Server"}]
    ok, _ = authorize_write(ENV, "Planning Sample", CFG, other)
    assert not ok
