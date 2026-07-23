from loguru import logger

from src.email.base import EmailProvider


class ConsoleEmailProvider(EmailProvider):
    """Dev-safe fallback used whenever SMTP isn't configured — logs the
    email instead of failing to send it. Never used when SMTP_HOST is set;
    see src/email/registry.py.

    Uses loguru, not stdlib logging — this codebase's only logging sink is
    configured in src/core/logging.py by reconfiguring loguru's global
    logger; stdlib logging.getLogger(...) calls have no handler attached
    and are silently dropped (confirmed live: caught this exact mistake
    because the token never showed up in logs/application.log)."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        logger.info(
            "EMAIL (console provider, no SMTP configured) to={} subject={!r}\n{}",
            to,
            subject,
            body,
        )
