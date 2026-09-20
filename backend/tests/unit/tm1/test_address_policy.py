"""Where a TM1 connection is allowed to point.

From a hosted deployment, a loopback, link-local or private address is
the platform's own network — and TM1py would send requests there with
whatever port and scheme the caller chose. The check runs on the IP
literal at save time; hostnames are the deployment's network policy.
"""

import pytest

from src.core.config import settings
from src.core.exceptions import ValidationException
from src.tm1.addressing import PRIVATE_ADDRESS_REFUSED, is_private_address
from src.tm1.service import _check_address_reachable_by_policy


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "localhost",
        "LOCALHOST",
        "::1",
        "[::1]",
        "169.254.169.254",  # cloud metadata
        "10.0.0.8",
        "172.16.5.5",
        "192.168.1.20",
        "0.0.0.0",
        "224.0.0.1",
    ],
)
def test_non_public_literals_are_private(address):
    assert is_private_address(address)


@pytest.mark.parametrize(
    "address",
    [
        "us-east-1.planninganalytics.saas.ibm.com",
        "tm1.example.com",
        "8.8.8.8",
        "2606:4700::1111",
    ],
)
def test_public_addresses_are_not(address):
    assert not is_private_address(address)


def test_policy_refuses_private_addresses_by_default(monkeypatch):
    monkeypatch.setattr(settings, "TM1_ALLOW_PRIVATE_ADDRESSES", False)

    with pytest.raises(ValidationException) as excinfo:
        _check_address_reachable_by_policy("169.254.169.254")

    assert excinfo.value.message == PRIVATE_ADDRESS_REFUSED


def test_policy_can_be_opened_for_a_self_hosted_deployment(monkeypatch):
    monkeypatch.setattr(settings, "TM1_ALLOW_PRIVATE_ADDRESSES", True)

    _check_address_reachable_by_policy("192.168.1.20")


def test_policy_lets_public_hosts_through(monkeypatch):
    monkeypatch.setattr(settings, "TM1_ALLOW_PRIVATE_ADDRESSES", False)

    _check_address_reachable_by_policy("tm1.example.com")
