import httpx
import respx
from sqlalchemy import select

from app.db.models import AuditLog, Invite
from tests.test_soap import fault, ok

SOAP = "http://soap.test/"


async def test_get_invite_states(client, make_invite):
    raw, _ = await make_invite(email="a@b.c")
    resp = await client.get(f"/api/v1/register/{raw}")
    assert resp.status_code == 200 and resp.json() == {"email": "a@b.c"}

    assert (await client.get("/api/v1/register/nonexistent")).status_code == 404
    raw, _ = await make_invite(used=True)
    assert (await client.get(f"/api/v1/register/{raw}")).status_code == 410
    raw, _ = await make_invite(revoked=True)
    assert (await client.get(f"/api/v1/register/{raw}")).status_code == 410
    raw, _ = await make_invite(days=-1)
    assert (await client.get(f"/api/v1/register/{raw}")).status_code == 410


async def test_check_username(client, make_invite, seed_account):
    await seed_account(1, "TAKEN")
    raw, _ = await make_invite()
    async def check(u):
        r = await client.get(f"/api/v1/register/{raw}/check-username",
                             params={"username": u})
        return r.json()
    assert await check("newname") == {"valid": True, "available": True}
    assert await check("taken") == {"valid": True, "available": False}
    assert (await check("x!"))["valid"] is False
    assert (await check("ab"))["valid"] is False
    assert (await check("a" * 21))["valid"] is False


async def test_check_username_requires_valid_invite(client):
    resp = await client.get("/api/v1/register/bogus/check-username",
                            params={"username": "abc"})
    assert resp.status_code == 404


@respx.mock
async def test_register_success(client, make_invite, seed_account, portal_db, app):
    raw, inv_id = await make_invite(email="new@player.com")
    route = respx.post(SOAP).mock(return_value=ok("Account created: NEWBIE"))

    async def create_side_effect(request):
        # after SOAP create, the account appears in acore_auth
        if b"account create" in request.content:
            from app.core.srp6 import calculate_verifier
            from app.services import acore
            from tests.conftest import SALT
            async with app.state.acore_engine.begin() as conn:
                await conn.execute(acore.account.insert().values(
                    id=42, username="NEWBIE", email=None, salt=SALT,
                    verifier=calculate_verifier("NEWBIE", "hunter2!!", SALT),
                    totp_secret=None))
        return ok("done")

    route.side_effect = create_side_effect
    resp = await client.post(f"/api/v1/register/{raw}",
                             json={"username": "Newbie", "password": "hunter2!!"})
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"username": "NEWBIE"}
    inv = await portal_db.get(Invite, inv_id)
    assert inv.used_at is not None and inv.account_id == 42
    actions = [l.action for l in (await portal_db.execute(select(AuditLog))).scalars()]
    assert "invite.redeemed" in actions and "account.created" in actions
    # second redeem attempt is blocked
    resp = await client.post(f"/api/v1/register/{raw}",
                             json={"username": "Other1", "password": "hunter2!!"})
    assert resp.status_code == 410


async def test_register_validation(client, make_invite):
    raw, _ = await make_invite()
    resp = await client.post(f"/api/v1/register/{raw}",
                             json={"username": "x!", "password": "hunter2!!"})
    assert resp.status_code == 422 and resp.json()["detail"] == "Invalid username"
    resp = await client.post(f"/api/v1/register/{raw}",
                             json={"username": "GoodName", "password": "short"})
    assert resp.status_code == 422 and resp.json()["detail"] == "Invalid password"
    resp = await client.post(f"/api/v1/register/{raw}",
                             json={"username": "GoodName", "password": "x" * 17})
    assert resp.status_code == 422


async def test_register_username_taken_locally(client, make_invite, seed_account):
    await seed_account(1, "TAKEN")
    raw, _ = await make_invite()
    resp = await client.post(f"/api/v1/register/{raw}",
                             json={"username": "taken", "password": "hunter2!!"})
    assert resp.status_code == 409


@respx.mock
async def test_register_soap_says_exists(client, make_invite):
    respx.post(SOAP).mock(return_value=fault("Account with this name already exist!"))
    raw, _ = await make_invite()
    resp = await client.post(f"/api/v1/register/{raw}",
                             json={"username": "Racer", "password": "hunter2!!"})
    assert resp.status_code == 409


@respx.mock
async def test_register_soap_down(client, make_invite, portal_db):
    respx.post(SOAP).mock(side_effect=httpx.ConnectError("down"))
    raw, inv_id = await make_invite()
    resp = await client.post(f"/api/v1/register/{raw}",
                             json={"username": "Newbie", "password": "hunter2!!"})
    assert resp.status_code == 503
    assert (await portal_db.get(Invite, inv_id)).used_at is None  # not half-applied


@respx.mock
async def test_register_email_set_failure_is_tolerated(client, make_invite, portal_db):
    def responder(request):
        if b"set email" in request.content:
            return fault("no such command")
        return ok("Account created")
    respx.post(SOAP).mock(side_effect=responder)
    raw, _ = await make_invite()
    resp = await client.post(f"/api/v1/register/{raw}",
                             json={"username": "Newbie", "password": "hunter2!!"})
    assert resp.status_code == 201
    logs = (await portal_db.execute(select(AuditLog))).scalars().all()
    created = next(l for l in logs if l.action == "account.created")
    assert created.detail["email_set"] is False
