from email.message import EmailMessage

import aiosmtplib

from app.core.config import Settings
from app.services import email_templates
from app.services.email_templates import EmailContent


class MailerError(Exception):
    pass


class Mailer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send_invite(self, to_email: str, link: str, expires_days: int) -> None:
        content = email_templates.invite(self._settings.server_name, link, expires_days)
        await self._send(self._build(to_email, content))

    async def send_password_reset(
        self, to_email: str, username: str, link: str, expires_hours: int
    ) -> None:
        content = email_templates.password_reset(
            self._settings.server_name, username, link, expires_hours
        )
        await self._send(self._build(to_email, content))

    def _build(self, to_email: str, content: EmailContent) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self._settings.smtp_from
        msg["To"] = to_email
        msg["Subject"] = content.subject
        msg.set_content(content.text)
        msg.add_alternative(content.html, subtype="html")
        return msg

    async def _send(self, msg: EmailMessage) -> None:
        s = self._settings
        try:
            username = s.smtp_user or None
            password = (s.smtp_pass or None) if username else None
            await aiosmtplib.send(
                msg,
                hostname=s.smtp_host,
                port=s.smtp_port,
                username=username,
                password=password,
                start_tls=s.smtp_starttls,
            )
        except (aiosmtplib.errors.SMTPException, OSError) as exc:
            raise MailerError(f"failed to send mail: {exc}") from exc

    async def send_email_change(self, to_email: str, link: str, expires_hours: int) -> None:
        content = email_templates.email_change(self._settings.server_name, link, expires_hours)
        await self._send(self._build(to_email, content))

    async def ping(self) -> bool:
        s = self._settings
        try:
            client = aiosmtplib.SMTP(hostname=s.smtp_host, port=s.smtp_port)
            await client.connect(timeout=5)
            await client.quit()
            return True
        except (aiosmtplib.errors.SMTPException, OSError):
            return False
