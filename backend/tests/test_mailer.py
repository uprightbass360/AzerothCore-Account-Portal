from email.message import EmailMessage
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.services.mailer import Mailer, MailerError


@pytest.fixture
def mailer():
    return Mailer(
        Settings(
            _env_file=None,
            smtp_host="mail.test",
            smtp_port=587,
            smtp_user="u",
            smtp_pass="p",
            smtp_from="noreply@t.co",
            public_base_url="http://portal.test",
        )
    )


async def test_send_invite(mailer):
    with patch("app.services.mailer.aiosmtplib.send", new_callable=AsyncMock) as send:
        await mailer.send_invite("new@player.com", "http://portal.test/register/tok", 7)
    msg = send.call_args.args[0]
    assert isinstance(msg, EmailMessage)
    assert msg["To"] == "new@player.com" and msg["From"] == "noreply@t.co"
    assert "http://portal.test/register/tok" in msg.get_body(("plain",)).get_content()
    assert "http://portal.test/register/tok" in msg.get_body(("html",)).get_content()
    kw = send.call_args.kwargs
    assert kw["hostname"] == "mail.test" and kw["port"] == 587
    assert kw["username"] == "u" and kw["password"] == "p" and kw["start_tls"] is True


async def test_send_invite_no_auth_when_no_user(mailer):
    mailer._settings.smtp_user = ""
    with patch("app.services.mailer.aiosmtplib.send", new_callable=AsyncMock) as send:
        await mailer.send_invite("a@b.c", "l", 7)
    kw = send.call_args.kwargs
    assert kw["username"] is None and kw["password"] is None


async def test_send_failure_raises(mailer):
    with (
        patch(
            "app.services.mailer.aiosmtplib.send",
            new_callable=AsyncMock,
            side_effect=OSError("refused"),
        ),
        pytest.raises(MailerError),
    ):
        await mailer.send_invite("a@b.c", "l", 7)


async def test_ping(mailer):
    with patch("app.services.mailer.aiosmtplib.SMTP") as smtp_cls:
        inst = smtp_cls.return_value
        inst.connect = AsyncMock()
        inst.quit = AsyncMock()
        assert await mailer.ping() is True
    with patch("app.services.mailer.aiosmtplib.SMTP") as smtp_cls:
        smtp_cls.return_value.connect = AsyncMock(side_effect=OSError("down"))
        assert await mailer.ping() is False


async def test_send_email_change(mailer):
    with patch("app.services.mailer.aiosmtplib.send", new_callable=AsyncMock) as send:
        await mailer.send_email_change(
            "new@addr.example", "http://portal.test/confirm-email/tok", 24
        )
    msg = send.call_args.args[0]
    assert msg["To"] == "new@addr.example"
    assert "Confirm your new email" in msg["Subject"]
    assert "http://portal.test/confirm-email/tok" in msg.get_body(("plain",)).get_content()
    assert "http://portal.test/confirm-email/tok" in msg.get_body(("html",)).get_content()
    assert "24 hours" in msg.get_body(("plain",)).get_content()


async def test_send_password_reset(mailer):
    with patch("app.services.mailer.aiosmtplib.send", new_callable=AsyncMock) as send:
        await mailer.send_password_reset(
            "v@m.example", "VICTIM", "http://portal.test/reset-password/tok", 48
        )
    msg = send.call_args.args[0]
    assert msg["To"] == "v@m.example"
    assert "VICTIM" in msg["Subject"]
    body = msg.get_body(("plain",)).get_content()
    assert "http://portal.test/reset-password/tok" in body
    assert "old password no longer works" in body
    assert "48 hours" in body
