import pytest
from loguru import logger

from src.core.config import settings
from src.email.console_provider import ConsoleEmailProvider
from src.email.registry import get_email_provider
from src.email.smtp_provider import SmtpEmailProvider


@pytest.mark.asyncio
async def test_console_provider_logs_instead_of_sending():
    # This app's only logging sink is loguru (src/core/logging.py
    # reconfigures its global logger) — pytest's stdlib-logging caplog
    # fixture can't see loguru output, so capture via a temporary sink
    # instead. Real gotcha: ConsoleEmailProvider originally used stdlib
    # logging.getLogger(...), which has no handler in this app and
    # silently drops everything — caught live, not by this test alone.
    messages: list[str] = []
    sink_id = logger.add(messages.append, level="INFO")

    try:
        provider = ConsoleEmailProvider()
        await provider.send(to="a@example.com", subject="Subject", body="Body text")
    finally:
        logger.remove(sink_id)

    combined = "".join(messages)
    assert "a@example.com" in combined
    assert "Body text" in combined


def test_registry_defaults_to_console_provider_when_smtp_unconfigured():
    original = settings.SMTP_HOST
    settings.SMTP_HOST = None
    try:
        assert isinstance(get_email_provider(), ConsoleEmailProvider)
    finally:
        settings.SMTP_HOST = original


def test_registry_uses_smtp_provider_when_configured():
    original = settings.SMTP_HOST
    settings.SMTP_HOST = "smtp.example.com"
    try:
        assert isinstance(get_email_provider(), SmtpEmailProvider)
    finally:
        settings.SMTP_HOST = original
