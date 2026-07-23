import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.core.config import settings
from src.email.base import EmailProvider
from src.email.exceptions import EmailDeliveryError


class SmtpEmailProvider(EmailProvider):

    def _send_sync(self, *, to: str, subject: str, body: str) -> None:
        message = MIMEMultipart()
        message["From"] = settings.SMTP_FROM_EMAIL
        message["To"] = to
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()

            if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)

            server.sendmail(settings.SMTP_FROM_EMAIL, [to], message.as_string())

    async def send(self, *, to: str, subject: str, body: str) -> None:
        try:
            # smtplib is synchronous — same asyncio.to_thread discipline
            # used for TM1py elsewhere in this codebase, so a slow/unreachable
            # SMTP server can't block the event loop.
            await asyncio.to_thread(self._send_sync, to=to, subject=subject, body=body)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailDeliveryError(f"Failed to send email: {exc}") from exc
