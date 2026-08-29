from unittest.mock import AsyncMock, patch

import respx
from sqlalchemy import select

from app.db.models import Invite, PortalSession
from app.services.mailer import MailerError
from tests.test_soap import ok

SOAP = "http://soap.test/"


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


async def test_admin_endpoints_require_admin(client, seed_account, login):
    await seed_account(1, "pleb")
    token = await login("pleb", "testpass")
    resp = await client.get("/api/v1/admin/invites", headers=bearer(token))
    assert resp.status_code == 403


async def test_invite_create_list_revoke(client, admin_login, portal_db):
    token = await admin_login()
    with patch("app.services.mailer.Mailer.send_invite", new_callable=AsyncMock) as send:
        resp = await client.post("/api/v1/admin/invites", headers=bearer(token),
                                 json={"email": "new@player.com"})
    assert resp.status_code == 201
    inv_id = resp.json()["id"]
    link = send.call_args.args[1]
    assert link.startswith("http://portal.test/register/")
    # raw token is in the link, only its hash is stored
    raw = link.rsplit("/", 1)[1]
    inv = await portal_db.get(Invite, inv_id)
    assert inv.token_hash != raw and len(inv.token_hash) == 64

    # re-invite same email revokes the old one
    with patch("app.services.mailer.Mailer.send_invite", new_callable=AsyncMock):
        resp2 = await client.post("/api/v1/admin/invites", headers=bearer(token),
                                  json={"email": "new@player.com"})
    assert resp2.status_code == 201
    await portal_db.refresh(inv)
    assert inv.revoked_at is not None

    resp = await client.get("/api/v1/admin/invites", headers=bearer(token))
    items = resp.json()["items"]
    assert len(items) == 1 and items[0]["email"] == "new@player.com"

    resp = await client.delete(f"/api/v1/admin/invites/{items[0]['id']}",
                               headers=bearer(token))
    assert resp.status_code == 200
    assert (await client.get("/api/v1/admin/invites",
                             headers=bearer(token))).json()["items"] == []
    resp = await client.delete("/api/v1/admin/invites/9999", headers=bearer(token))
    assert resp.status_code == 404


async def test_invite_email_failure(client, admin_login, portal_db):
    token = await admin_login()
    with patch("app.services.mailer.Mailer.send_invite", new_callable=AsyncMock,
               side_effect=MailerError("refused")):
        resp = await client.post("/api/v1/admin/invites", headers=bearer(token),
                                 json={"email": "x@y.z"})
    assert resp.status_code == 502
    assert (await portal_db.execute(select(Invite))).scalars().all() == []


async def test_invite_bad_email(client, admin_login):
    token = await admin_login()
    resp = await client.post("/api/v1/admin/invites", headers=bearer(token),
                             json={"email": "not-an-email"})
    assert resp.status_code == 422


async def test_accounts_list(client, admin_login, seed_account, portal_db, app):
    token = await admin_login(90, "boss")
    await seed_account(1, "ALPHA", totp_raw=b"\x0a" * 10)
    await seed_account(2, "BETA")
    from app.services import acore
    async with app.state.acore_engine.begin() as conn:
        await conn.execute(acore.account_banned.insert().values(
            id=2, bandate=1, unbandate=0, bannedby="portal", banreason="r", active=1))
    from app.db.base import utcnow
    portal_db.add(Invite(email="a@b.c", token_hash="h" * 64, created_by=90,
                         expires_at=utcnow(), account_id=1))
    await portal_db.commit()
    resp = await client.get("/api/v1/admin/accounts", headers=bearer(token))
    body = resp.json()
    assert body["total"] == 3 and body["pages"] == 1
    by_name = {i["username"]: i for i in body["items"]}
    assert by_name["ALPHA"]["totp_enabled"] is True
    assert by_name["ALPHA"]["invited_email"] == "a@b.c"
    assert by_name["BETA"]["locked"] is True
    assert by_name["BOSS"]["is_admin"] is True
    resp = await client.get("/api/v1/admin/accounts", headers=bearer(token),
                            params={"search": "alp"})
    assert resp.json()["total"] == 1


@respx.mock
async def test_lock_unlock(client, admin_login, seed_account, login, portal_db):
    token = await admin_login()
    await seed_account(1, "victim")
    victim_token = await login("victim", "testpass")
    route = respx.post(SOAP).mock(return_value=ok("done"))
    resp = await client.post("/api/v1/admin/accounts/victim/lock", headers=bearer(token))
    assert resp.status_code == 200
    assert b"ban account VICTIM -1" in route.calls.last.request.content
    sessions = (await portal_db.execute(
        select(PortalSession).where(PortalSession.account_id == 1))).scalars().all()
    assert all(s.revoked_at is not None for s in sessions)
    resp = await client.get("/api/v1/user", headers=bearer(victim_token))
    assert resp.status_code == 401

    resp = await client.post("/api/v1/admin/accounts/victim/unlock", headers=bearer(token))
    assert resp.status_code == 200
    assert b"unban account VICTIM" in route.calls.last.request.content

    assert (await client.post("/api/v1/admin/accounts/ghost/lock",
                              headers=bearer(token))).status_code == 404
    assert (await client.post("/api/v1/admin/accounts/boss/lock",
                              headers=bearer(token))).status_code == 400  # self


@respx.mock
async def test_unlock_unknown_account_404(client, admin_login):
    token = await admin_login()
    respx.post(SOAP).mock(return_value=ok("done"))
    resp = await client.post("/api/v1/admin/accounts/ghost/unlock", headers=bearer(token))
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Account not found"


async def test_admins_crud(client, admin_login, seed_account, portal_db):
    token = await admin_login(90, "boss")
    await seed_account(1, "newmin")
    resp = await client.get("/api/v1/admin/admins", headers=bearer(token))
    assert [a["account_id"] for a in resp.json()["items"]] == [90]

    resp = await client.post("/api/v1/admin/admins", headers=bearer(token),
                             json={"username": "newmin"})
    assert resp.status_code == 201
    resp = await client.post("/api/v1/admin/admins", headers=bearer(token),
                             json={"username": "newmin"})
    assert resp.status_code == 409
    resp = await client.post("/api/v1/admin/admins", headers=bearer(token),
                             json={"username": "ghost"})
    assert resp.status_code == 404

    resp = await client.delete("/api/v1/admin/admins/1", headers=bearer(token))
    assert resp.status_code == 200
    resp = await client.delete("/api/v1/admin/admins/90", headers=bearer(token))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Cannot remove the last admin"
    resp = await client.delete("/api/v1/admin/admins/1", headers=bearer(token))
    assert resp.status_code == 404


async def test_audit_list(client, admin_login):
    token = await admin_login()  # produces login.success audit rows
    resp = await client.get("/api/v1/admin/audit", headers=bearer(token))
    body = resp.json()
    assert body["total"] >= 1
    assert body["items"][0]["action"] in ("login.success", "admin.granted")
    resp = await client.get("/api/v1/admin/audit", headers=bearer(token),
                            params={"action": "nonexistent.action"})
    assert resp.json()["total"] == 0
