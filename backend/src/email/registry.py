from src.core.config import settings
from src.email.base import EmailProvider
from src.email.console_provider import ConsoleEmailProvider
from src.email.smtp_provider import SmtpEmailProvider

_console_provider = ConsoleEmailProvider()
_smtp_provider = SmtpEmailProvider()


def get_email_provider() -> EmailProvider:
    if settings.SMTP_HOST:
        return _smtp_provider

    return _console_provider
