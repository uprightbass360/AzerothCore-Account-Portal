from email.message import EmailMessage

import aiosmtplib

from app.core.config import Settings


class MailerError(Exception):
    pass


class Mailer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send_invite(self, to_email: str, link: str, expires_days: int) -> None:
        s = self._settings
        msg = EmailMessage()
        msg["From"] = s.smtp_from
        msg["To"] = to_email
        msg["Subject"] = f"You're invited to join {s.totp_issuer}"
        text = (
            f"You've been invited to create a game account on {s.totp_issuer}.\n\n"
            f"Register here: {link}\n\n"
            f"This invite expires in {expires_days} days."
        )
        msg.set_content(text)
        msg.add_alternative(
            f"<p>You've been invited to create a game account on <b>{s.totp_issuer}</b>.</p>"
            f'<p><a href="{link}">Create your account</a></p>'
            f"<p>This invite expires in {expires_days} days.</p>",
            subtype="html",
        )
        await self._send(msg)

    async def send_password_reset(
        self, to_email: str, username: str, link: str, expires_hours: int
    ) -> None:
        s = self._settings
        msg = EmailMessage()
        msg["From"] = s.smtp_from
        msg["To"] = to_email
        msg["Subject"] = f"Set a new password for {username} on {s.totp_issuer}"
        text = (
            f"An administrator reset the password for your {s.totp_issuer} account {username}.\n"
            f"Your old password no longer works.\n\n"
            f"Choose a new password here: {link}\n\n"
            f"This link expires in {expires_hours} hours."
        )
        msg.set_content(text)
        msg.add_alternative(
            f"<p>An administrator reset the password for your <b>{s.totp_issuer}</b> account "
            f"<b>{username}</b>. Your old password no longer works.</p>"
            f'<p><a href="{link}">Choose a new password</a></p>'
            f"<p>This link expires in {expires_hours} hours.</p>",
            subtype="html",
        )
        await self._send(msg)

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
        s = self._settings
        msg = EmailMessage()
        msg["From"] = s.smtp_from
        msg["To"] = to_email
        msg["Subject"] = f"Confirm your new email for {s.totp_issuer}"
        text = (
            f"A request was made to use this address for a {s.totp_issuer} game account.\n\n"
            f"Confirm the change here: {link}\n\n"
            f"This link expires in {expires_hours} hours. If you didn't request this, ignore this email."
        )
        msg.set_content(text)
        msg.add_alternative(
            f"<p>A request was made to use this address for a <b>{s.totp_issuer}</b> game account.</p>"
            f'<p><a href="{link}">Confirm the email change</a></p>'
            f"<p>This link expires in {expires_hours} hours. If you didn't request this, ignore this email.</p>",
            subtype="html",
        )
        await self._send(msg)

    async def ping(self) -> bool:
        s = self._settings
        try:
            client = aiosmtplib.SMTP(hostname=s.smtp_host, port=s.smtp_port)
            await client.connect(timeout=5)
            await client.quit()
            return True
        except (aiosmtplib.errors.SMTPException, OSError):
            return False
