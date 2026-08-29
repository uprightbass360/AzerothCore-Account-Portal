import base64

import pyotp
import respx
from sqlalchemy import select

from app.db.models import Admin, AuditLog, PortalSession
from tests.test_soap import ok

SOAP = "http://soap.test/"


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


async def test_get_user(client, seed_account, login, portal_db):
    await seed_account(1, "testuser", email="me@x.y")
    token = await login()
    resp = await client.get("/api/v1/user", headers=bearer(token))
    assert resp.json() == {"username": "TESTUSER", "email": "me@x.y",
                           "totp_enabled": False, "is_admin": False}
    portal_db.add(Admin(account_id=1, username="TESTUSER", granted_by=None))
    await portal_db.commit()
    resp = await client.get("/api/v1/user", headers=bearer(token))
    assert resp.json()["is_admin"] is True


async def test_get_user_account_gone(client, seed_account, login, app):
    await seed_account(1, "testuser")
    token = await login()
    from app.services import acore
    async with app.state.acore_engine.begin() as conn:
        await conn.execute(acore.account.delete())
    resp = await client.get("/api/v1/user", headers=bearer(token))
    assert resp.status_code == 401


@respx.mock
async def test_change_password(client, seed_account, login, portal_db):
    await seed_account(1, "testuser")
    token1 = await login()
    token2 = await login()
    route = respx.post(SOAP).mock(return_value=ok("done"))
    resp = await client.post("/api/v1/user/password", headers=bearer(token2),
                             json={"current_password": "testpass",
                                   "new_password": "newpass99"})
    assert resp.status_code == 200
    assert b"account set password TESTUSER newpass99 newpass99" in \
        route.calls.last.request.content
    sessions = (await portal_db.execute(select(PortalSession))).scalars().all()
    revoked = {s.revoked_at is not None for s in sessions}
    assert revoked == {True, False}  # other session revoked, current kept
    resp = await client.get("/api/v1/user", headers=bearer(token1))
    assert resp.status_code == 401


async def test_change_password_wrong_current(client, seed_account, login):
    await seed_account(1, "testuser")
    token = await login()
    resp = await client.post("/api/v1/user/password", headers=bearer(token),
                             json={"current_password": "wrongwrong",
                                   "new_password": "newpass99"})
    assert resp.status_code == 403
    resp = await client.post("/api/v1/user/password", headers=bearer(token),
                             json={"current_password": "testpass",
                                   "new_password": "short"})
    assert resp.status_code == 422


@respx.mock
async def test_2fa_setup_confirm(client, seed_account, login, portal_db, app):
    await seed_account(1, "testuser")
    token = await login()
    resp = await client.post("/api/v1/user/2fa/setup", headers=bearer(token))
    body = resp.json()
    assert resp.status_code == 200
    assert len(body["secret"]) == 16
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert body["qr_svg"].startswith("<svg")
    # wrong code
    resp = await client.post("/api/v1/user/2fa/confirm", headers=bearer(token),
                             json={"code": "000001"})
    assert resp.status_code == 400 and resp.json()["detail"] == "Invalid code"
    # right code
    route = respx.post(SOAP).mock(return_value=ok("done"))
    good = pyotp.TOTP(body["secret"]).now()
    resp = await client.post("/api/v1/user/2fa/confirm", headers=bearer(token),
                             json={"code": good})
    assert resp.status_code == 200
    assert f"account set 2fa TESTUSER {body['secret']}".encode() in \
        route.calls.last.request.content
    sess = (await portal_db.execute(select(PortalSession))).scalar_one()
    assert sess.pending_totp_secret is None
    actions = [l.action for l in (await portal_db.execute(select(AuditLog))).scalars()]
    assert "2fa.enabled" in actions


async def test_2fa_setup_already_enabled(client, seed_account, login):
    await seed_account(1, "testuser", totp_raw=b"\x0a" * 10)
    # login needs the 2fa step now
    secret = base64.b32encode(b"\x0a" * 10).decode()
    resp = await client.post("/api/v1/auth/login/2fa",
                             json={"username": "testuser", "password": "testpass",
                                   "code": pyotp.TOTP(secret).now()})
    token = resp.json()["token"]
    resp = await client.post("/api/v1/user/2fa/setup", headers=bearer(token))
    assert resp.status_code == 409


async def test_2fa_confirm_without_setup(client, seed_account, login):
    await seed_account(1, "testuser")
    token = await login()
    resp = await client.post("/api/v1/user/2fa/confirm", headers=bearer(token),
                             json={"code": "123456"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "No 2FA setup in progress"


@respx.mock
async def test_2fa_disable(client, seed_account):
    raw = b"\x0a" * 10
    secret = base64.b32encode(raw).decode()
    await seed_account(1, "testuser", totp_raw=raw)
    resp = await client.post("/api/v1/auth/login/2fa",
                             json={"username": "testuser", "password": "testpass",
                                   "code": pyotp.TOTP(secret).now()})
    token = resp.json()["token"]
    # wrong password
    resp = await client.post("/api/v1/user/2fa/disable", headers=bearer(token),
                             json={"password": "wrongwrong", "code": pyotp.TOTP(secret).now()})
    assert resp.status_code == 403
    # wrong code
    resp = await client.post("/api/v1/user/2fa/disable", headers=bearer(token),
                             json={"password": "testpass", "code": "000001"})
    assert resp.status_code == 400
    # success
    route = respx.post(SOAP).mock(return_value=ok("done"))
    resp = await client.post("/api/v1/user/2fa/disable", headers=bearer(token),
                             json={"password": "testpass", "code": pyotp.TOTP(secret).now()})
    assert resp.status_code == 200
    assert b"account set 2fa TESTUSER off" in route.calls.last.request.content


async def test_2fa_disable_not_enabled(client, seed_account, login):
    await seed_account(1, "testuser")
    token = await login()
    resp = await client.post("/api/v1/user/2fa/disable", headers=bearer(token),
                             json={"password": "testpass", "code": "123456"})
    assert resp.status_code == 400
