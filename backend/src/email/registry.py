from loguru import logger

from src.core.config import settings
from src.email.base import EmailProvider
from src.email.console_provider import ConsoleEmailProvider
from src.email.smtp_provider import SmtpEmailProvider


class UnconfiguredEmailProvider(EmailProvider):
    """Production with no SMTP: the message is not delivered, and its body
    is not logged either.

    The console provider prints the whole email, which in development is
    the point. In a hosted deployment the log stream is retained, shared
    and searchable — and the body of a password-reset email is a link
    that sets the password of whoever clicks it.
    """

    async def send(self, *, to: str, subject: str, body: str) -> None:
        logger.warning(
            "No email provider is configured (SMTP_HOST unset); a message "
            "to {} with subject {!r} was not sent.",
            to,
            subject,
        )


_console_provider = ConsoleEmailProvider()
_smtp_provider = SmtpEmailProvider()
_unconfigured_provider = UnconfiguredEmailProvider()


def get_email_provider() -> EmailProvider:
    if settings.SMTP_HOST:
        return _smtp_provider

    if settings.DEBUG:
        return _console_provider

    return _unconfigured_provider
