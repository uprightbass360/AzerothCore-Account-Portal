import base64
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pyotp
import respx
from sqlalchemy import select

from app.core.security import new_session_token
from app.db.base import utcnow
from app.db.models import AuditLog, PasswordReset
from app.services.mailer import MailerError
from tests.conftest import make_sessionmaker
from tests.test_soap import ok

SOAP = "http://soap.test/"


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@respx.mock
async def test_admin_reset_scrambles_and_mails(client, admin_login, seed_account, login, portal_db):
    token = await admin_login(90, "boss")
    await seed_account(1, "victim", email="victim@mail.example")
    victim_session = await login("victim", "testpass")
    route = respx.post(SOAP).mock(return_value=ok("done"))
    with patch("app.services.mailer.Mailer.send_password_reset", new_callable=AsyncMock) as send:
        resp = await client.post(
            "/api/v1/admin/accounts/victim/reset-password", headers=bearer(token)
        )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "sent_to": "victim@mail.example"}
    # password scrambled via SOAP to a random value (not the old one)
    assert b"account set password VICTIM " in route.calls.last.request.content
    assert b"testpass" not in route.calls.last.request.content
    # victim's sessions revoked
    resp = await client.get("/api/v1/user", headers=bearer(victim_session))
    assert resp.status_code == 401
    # pending row + audit
    row = (await portal_db.execute(select(PasswordReset))).scalar_one()
    assert row.account_id == 1 and row.used_at is None
    link = send.call_args.args[2]
    assert link.startswith("http://portal.test/reset-password/")
    actions = [a.action for a in (await portal_db.execute(select(AuditLog))).scalars()]
    assert "password.reset_initiated" in actions


@respx.mock
async def test_admin_reset_reissue_replaces(client, admin_login, seed_account, portal_db):
    token = await admin_login(90, "boss")
    await seed_account(1, "victim", email="v@m.example")
    respx.post(SOAP).mock(return_value=ok("done"))
    with patch("app.services.mailer.Mailer.send_password_reset", new_callable=AsyncMock):
        await client.post("/api/v1/admin/accounts/victim/reset-password", headers=bearer(token))
        await client.post("/api/v1/admin/accounts/victim/reset-password", headers=bearer(token))
    rows = (await portal_db.execute(select(PasswordReset))).scalars().all()
    assert len(rows) == 1


async def test_admin_reset_guards(client, admin_login, seed_account, portal_db):
    token = await admin_login(90, "boss")
    resp = await client.post("/api/v1/admin/accounts/ghost/reset-password", headers=bearer(token))
    assert resp.status_code == 404
    await seed_account(1, "noemail", email=None)
    resp = await client.post("/api/v1/admin/accounts/noemail/reset-password", headers=bearer(token))
    assert resp.status_code == 409
    await seed_account(2, "victim", email="v@m.example")
    with patch(
        "app.services.mailer.Mailer.send_password_reset",
        new_callable=AsyncMock,
        side_effect=MailerError("refused"),
    ):
        resp = await client.post(
            "/api/v1/admin/accounts/victim/reset-password", headers=bearer(token)
        )
    assert resp.status_code == 502
    assert (await portal_db.execute(select(PasswordReset))).scalars().all() == []


async def make_reset_row(app, account_id=1, hours=48, used=False):
    raw, hashed = new_session_token()
    maker = make_sessionmaker(app.state.engine)
    async with maker() as db:
        db.add(
            PasswordReset(
                account_id=account_id,
                token_hash=hashed,
                expires_at=utcnow() + timedelta(hours=hours),
                used_at=utcnow() if used else None,
            )
        )
        await db.commit()
    return raw


async def test_reset_info_states(client, app, seed_account):
    await seed_account(1, "victim", totp_raw=b"\x0a" * 10)
    raw = await make_reset_row(app)
    resp = await client.get(f"/api/v1/password-reset/{raw}")
    assert resp.status_code == 200
    assert resp.json() == {"username": "VICTIM", "totp_required": True}
    assert (await client.get("/api/v1/password-reset/bogus")).status_code == 404
    used = await make_reset_row(app, used=True)
    assert (await client.get(f"/api/v1/password-reset/{used}")).status_code == 410
    expired = await make_reset_row(app, hours=-1)
    assert (await client.get(f"/api/v1/password-reset/{expired}")).status_code == 410
    orphan = await make_reset_row(app, account_id=999)
    assert (await client.get(f"/api/v1/password-reset/{orphan}")).status_code == 410


@respx.mock
async def test_reset_complete_success_and_replay(client, app, seed_account, portal_db):
    await seed_account(1, "victim")
    raw = await make_reset_row(app)
    route = respx.post(SOAP).mock(return_value=ok("done"))
    resp = await client.post(f"/api/v1/password-reset/{raw}", json={"new_password": "brandNew99"})
    assert resp.status_code == 200 and resp.json() == {"ok": True, "username": "VICTIM"}
    assert b"account set password VICTIM brandNew99 brandNew99" in route.calls.last.request.content
    actions = [a.action for a in (await portal_db.execute(select(AuditLog))).scalars()]
    assert "password.reset" in actions
    resp = await client.post(f"/api/v1/password-reset/{raw}", json={"new_password": "brandNew99"})
    assert resp.status_code == 410


@respx.mock
async def test_reset_complete_validations(client, app, seed_account):
    raw_secret = b"\x0a" * 10
    secret = base64.b32encode(raw_secret).decode()
    await seed_account(1, "victim", totp_raw=raw_secret)
    raw = await make_reset_row(app)
    resp = await client.post(f"/api/v1/password-reset/{raw}", json={"new_password": "short"})
    assert resp.status_code == 422
    resp = await client.post(f"/api/v1/password-reset/{raw}", json={"new_password": "brandNew99"})
    assert resp.status_code == 400 and resp.json()["detail"] == "2FA code required"
    resp = await client.post(
        f"/api/v1/password-reset/{raw}", json={"new_password": "brandNew99", "code": "000001"}
    )
    assert resp.status_code == 400 and resp.json()["detail"] == "Invalid code"
    respx.post(SOAP).mock(return_value=ok("done"))
    resp = await client.post(
        f"/api/v1/password-reset/{raw}",
        json={"new_password": "brandNew99", "code": pyotp.TOTP(secret).now()},
    )
    assert resp.status_code == 200


@respx.mock
async def test_reset_complete_soap_down(client, app, seed_account, portal_db):
    await seed_account(1, "victim")
    raw = await make_reset_row(app)
    respx.post(SOAP).mock(side_effect=httpx.ConnectError("down"))
    resp = await client.post(f"/api/v1/password-reset/{raw}", json={"new_password": "brandNew99"})
    assert resp.status_code == 503
    row = (await portal_db.execute(select(PasswordReset))).scalar_one()
    assert row.used_at is None


async def test_reset_complete_account_gone(client, app):
    raw = await make_reset_row(app, account_id=999)
    resp = await client.post(f"/api/v1/password-reset/{raw}", json={"new_password": "brandNew99"})
    assert resp.status_code == 410


async def test_reset_revokes_new_sessions_on_complete(client, app, seed_account, login):
    # a session created between scramble and completion also dies at completion
    await seed_account(1, "victim")
    raw = await make_reset_row(app)
    victim_session = await login("victim", "testpass")
    with respx.mock:
        respx.post(SOAP).mock(return_value=ok("done"))
        await client.post(f"/api/v1/password-reset/{raw}", json={"new_password": "brandNew99"})
    resp = await client.get("/api/v1/user", headers=bearer(victim_session))
    assert resp.status_code == 401
