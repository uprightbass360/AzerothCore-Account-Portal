import base64
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pyotp
import respx
from sqlalchemy import select

from app.core.security import new_session_token
from app.db.base import utcnow
from app.db.models import AuditLog, EmailChange
from app.services.mailer import MailerError
from tests.conftest import make_sessionmaker
from tests.test_soap import ok

SOAP = "http://soap.test/"


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


async def request_change(client, token, email="new@addr.example", password="testpass", code=None):
    payload = {"new_email": email, "password": password}
    if code is not None:
        payload["code"] = code
    return await client.post("/api/v1/user/email", headers=bearer(token), json=payload)


async def test_request_creates_pending_change(client, seed_account, login, portal_db):
    await seed_account(1, "testuser")
    token = await login()
    with patch("app.services.mailer.Mailer.send_email_change", new_callable=AsyncMock) as send:
        resp = await request_change(client, token)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "sent_to": "new@addr.example"}
    link = send.call_args.args[1]
    assert link.startswith("http://portal.test/confirm-email/")
    change = (await portal_db.execute(select(EmailChange))).scalar_one()
    assert change.account_id == 1 and change.new_email == "new@addr.example"
    assert change.token_hash != link.rsplit("/", 1)[1]
    actions = [a.action for a in (await portal_db.execute(select(AuditLog))).scalars()]
    assert "email.change_requested" in actions


async def test_request_replaces_pending(client, seed_account, login, portal_db):
    await seed_account(1, "testuser")
    token = await login()
    with patch("app.services.mailer.Mailer.send_email_change", new_callable=AsyncMock):
        await request_change(client, token, email="first@addr.example")
        await request_change(client, token, email="second@addr.example")
    changes = (await portal_db.execute(select(EmailChange))).scalars().all()
    assert [c.new_email for c in changes] == ["second@addr.example"]


async def test_request_wrong_password_and_bad_email(client, seed_account, login):
    await seed_account(1, "testuser")
    token = await login()
    resp = await request_change(client, token, password="wrongwrong")
    assert resp.status_code == 403
    resp = await request_change(client, token, email="not-an-email")
    assert resp.status_code == 422


async def test_request_requires_2fa_code(client, seed_account):
    raw = b"\x0a" * 10
    secret = base64.b32encode(raw).decode()
    await seed_account(1, "testuser", totp_raw=raw)
    resp = await client.post(
        "/api/v1/auth/login/2fa",
        json={"username": "testuser", "password": "testpass", "code": pyotp.TOTP(secret).now()},
    )
    token = resp.json()["token"]
    resp = await request_change(client, token)
    assert resp.status_code == 400 and resp.json()["detail"] == "2FA code required"
    resp = await request_change(client, token, code="000001")
    assert resp.status_code == 400 and resp.json()["detail"] == "Invalid code"
    with patch("app.services.mailer.Mailer.send_email_change", new_callable=AsyncMock):
        resp = await request_change(client, token, code=pyotp.TOTP(secret).now())
    assert resp.status_code == 200


async def test_request_mail_failure_is_atomic(client, seed_account, login, portal_db):
    await seed_account(1, "testuser")
    token = await login()
    with patch(
        "app.services.mailer.Mailer.send_email_change",
        new_callable=AsyncMock,
        side_effect=MailerError("refused"),
    ):
        resp = await request_change(client, token)
    assert resp.status_code == 502
    assert (await portal_db.execute(select(EmailChange))).scalars().all() == []


async def make_change_row(app, account_id=1, email="new@addr.example", hours=24, used=False):
    raw, hashed = new_session_token()
    maker = make_sessionmaker(app.state.engine)
    async with maker() as db:
        db.add(
            EmailChange(
                account_id=account_id,
                new_email=email,
                token_hash=hashed,
                expires_at=utcnow() + timedelta(hours=hours),
                used_at=utcnow() if used else None,
            )
        )
        await db.commit()
    return raw


async def test_confirm_info_states(client, app, seed_account):
    await seed_account(1, "testuser")
    raw = await make_change_row(app)
    resp = await client.get(f"/api/v1/email-change/{raw}")
    assert resp.status_code == 200 and resp.json() == {"new_email": "new@addr.example"}
    assert (await client.get("/api/v1/email-change/bogus")).status_code == 404
    used = await make_change_row(app, used=True)
    assert (await client.get(f"/api/v1/email-change/{used}")).status_code == 410
    expired = await make_change_row(app, hours=-1)
    assert (await client.get(f"/api/v1/email-change/{expired}")).status_code == 410


@respx.mock
async def test_confirm_success(client, app, seed_account, portal_db):
    await seed_account(1, "testuser")
    raw = await make_change_row(app)
    route = respx.post(SOAP).mock(return_value=ok("Email set"))
    resp = await client.post(f"/api/v1/email-change/{raw}")
    assert resp.status_code == 200 and resp.json() == {
        "ok": True,
        "username": "TESTUSER",
        "new_email": "new@addr.example",
    }
    assert b"account set email TESTUSER new@addr.example new@addr.example" in (
        route.calls.last.request.content
    )
    change = (await portal_db.execute(select(EmailChange))).scalar_one()
    assert change.used_at is not None
    actions = [a.action for a in (await portal_db.execute(select(AuditLog))).scalars()]
    assert "email.changed" in actions
    # replay is blocked
    assert (await client.post(f"/api/v1/email-change/{raw}")).status_code == 410


@respx.mock
async def test_confirm_soap_down_not_half_applied(client, app, seed_account, portal_db):
    import httpx

    await seed_account(1, "testuser")
    raw = await make_change_row(app)
    respx.post(SOAP).mock(side_effect=httpx.ConnectError("down"))
    resp = await client.post(f"/api/v1/email-change/{raw}")
    assert resp.status_code == 503
    change = (await portal_db.execute(select(EmailChange))).scalar_one()
    assert change.used_at is None


async def test_confirm_account_gone(client, app):
    raw = await make_change_row(app, account_id=999)
    resp = await client.post(f"/api/v1/email-change/{raw}")
    assert resp.status_code == 410
