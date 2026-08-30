import base64

import pyotp
from sqlalchemy import select

from app.db.models import AuditLog, PortalSession


async def test_login_success(client, seed_account, portal_db):
    await seed_account(1, "testuser")
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "TestUser", "password": "testpass"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body and "expires_at" in body
    assert body["expires_at"].endswith("Z")  # explicit UTC, not naive local time
    sess = (await portal_db.execute(select(PortalSession))).scalar_one()
    assert sess.account_id == 1 and sess.username == "TESTUSER"
    log = (await portal_db.execute(select(AuditLog))).scalar_one()
    assert log.action == "login.success"


async def test_login_wrong_password_and_unknown_user(client, seed_account, portal_db):
    await seed_account(1, "testuser")
    for creds in (
        {"username": "testuser", "password": "nope-nope"},
        {"username": "ghost", "password": "whatever1"},
    ):
        resp = await client.post("/api/v1/auth/login", json=creds)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid username or password"
    logs = (await portal_db.execute(select(AuditLog))).scalars().all()
    assert [l.action for l in logs] == ["login.failed", "login.failed"]


async def test_login_banned_account_generic_failure(client, seed_account, app):
    await seed_account(1, "testuser")
    from app.services import acore

    async with app.state.acore_engine.begin() as conn:
        await conn.execute(
            acore.account_banned.insert().values(
                id=1, bandate=1, unbandate=0, bannedby="portal", banreason="r", active=1
            )
        )
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "testuser", "password": "testpass"}
    )
    assert resp.status_code == 401


async def test_login_2fa_flow(client, seed_account):
    secret_raw = b"\x0a" * 10
    await seed_account(1, "testuser", totp_raw=secret_raw)
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "testuser", "password": "testpass"}
    )
    assert resp.status_code == 200 and resp.json() == {"status": "2fa_required"}
    secret = base64.b32encode(secret_raw).decode()
    good = pyotp.TOTP(secret).now()
    resp = await client.post(
        "/api/v1/auth/login/2fa",
        json={"username": "testuser", "password": "testpass", "code": good},
    )
    assert resp.status_code == 200 and "token" in resp.json()


async def test_login_2fa_wrong_code_and_wrong_password(client, seed_account):
    await seed_account(1, "testuser", totp_raw=b"\x0a" * 10)
    resp = await client.post(
        "/api/v1/auth/login/2fa",
        json={"username": "testuser", "password": "testpass", "code": "000001"},
    )
    assert resp.status_code == 401 and resp.json()["detail"] == "Invalid code"
    resp = await client.post(
        "/api/v1/auth/login/2fa",
        json={"username": "testuser", "password": "wrongpw12", "code": "000001"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


async def test_login_rate_limited(client, seed_account):
    await seed_account(1, "testuser")
    for _ in range(5):
        await client.post(
            "/api/v1/auth/login", json={"username": "testuser", "password": "badbadbad"}
        )
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "testuser", "password": "testpass"}
    )
    assert resp.status_code == 429


async def test_logout(client, seed_account, login, portal_db):
    await seed_account(1, "testuser")
    token = await login()
    resp = await client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200 and resp.json() == {"ok": True}
    sess = (await portal_db.execute(select(PortalSession))).scalar_one()
    assert sess.revoked_at is not None
    resp = await client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_logout_requires_bearer(client):
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 401
    resp = await client.post("/api/v1/auth/logout", headers={"Authorization": "Bearer bogus"})
    assert resp.status_code == 401


async def test_login_uses_forwarded_client_ip(client, seed_account, portal_db):
    await seed_account(1, "testuser")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "testuser", "password": "testpass"},
        headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.2"},
    )
    assert resp.status_code == 200
    log = (await portal_db.execute(select(AuditLog))).scalar_one()
    assert log.detail == {"ip": "203.0.113.7"}
