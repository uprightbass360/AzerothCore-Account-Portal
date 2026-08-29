import httpx
import respx
from sqlalchemy import select

from app.db.models import Admin
from app.main import create_app
from tests.test_soap import ok


async def test_health_all_ok(client, monkeypatch):
    async def ping_ok(self):
        return True

    monkeypatch.setattr("app.services.mailer.Mailer.ping", ping_ok)
    with respx.mock:
        respx.post("http://soap.test/").mock(return_value=ok("AzerothCore rev"))
        resp = await client.get("/api/v1/health")
    body = resp.json()
    assert resp.status_code == 200
    assert body["status"] == "ok"
    assert body["checks"] == {"acore_auth": "ok", "soap": "ok", "smtp": "ok"}


async def test_health_degraded(client, monkeypatch):
    async def ping_fail(self):
        return False

    monkeypatch.setattr("app.services.mailer.Mailer.ping", ping_fail)
    with respx.mock:
        respx.post("http://soap.test/").mock(side_effect=httpx.ConnectError("down"))
        resp = await client.get("/api/v1/health")
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["soap"] == "error" and body["checks"]["smtp"] == "warn"


async def test_health_acore_down(app, client):
    await app.state.acore_engine.dispose()
    app.state.reader._engine = None  # force ping failure
    with respx.mock:
        respx.post("http://soap.test/").mock(return_value=ok("x"))
        resp = await client.get("/api/v1/health")
    assert resp.json()["checks"]["acore_auth"] == "error"


async def test_health_needs_no_internal_key(client):
    with respx.mock:
        respx.post("http://soap.test/").mock(side_effect=httpx.ConnectError("down"))
        resp = await client.get("/api/v1/health", headers={"X-Internal-Key": ""})
    assert resp.status_code == 200


async def test_internal_key_required(client):
    resp = await client.post(
        "/api/v1/auth/login",
        headers={"X-Internal-Key": "wrong"},
        json={"username": "a", "password": "b"},
    )
    assert resp.status_code == 401


async def test_internal_key_non_ascii_header_is_rejected_not_500(client):
    # Header values travel over the wire as raw bytes; simulate a client sending
    # non-ASCII garbage rather than a valid key (previously raised TypeError -> 500).
    resp = await client.post(
        "/api/v1/auth/login",
        headers={"X-Internal-Key": b"wrong-\xe9\xe8\xea"},
        json={"username": "a", "password": "b"},
    )
    assert resp.status_code == 401


async def test_docs_and_openapi_require_internal_key(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        resp = await client.get(path, headers={"X-Internal-Key": "wrong"})
        assert resp.status_code in (401, 404)
        assert "swagger" not in resp.text.lower()
        assert "openapi" not in resp.text.lower()
    resp = await client.get("/api/v1/health", headers={"X-Internal-Key": "wrong"})
    assert resp.status_code == 200


async def test_admin_seeding(settings, seed_account, portal_db):
    from tests.conftest import _create_schemas

    await _create_schemas(settings)
    settings.admin_usernames = "ADMIN,GHOST"
    app = create_app(settings)
    async with app.state.acore_engine.begin() as conn:
        from app.core.srp6 import calculate_verifier
        from app.services import acore
        from tests.conftest import SALT

        await conn.execute(
            acore.account.insert().values(
                id=9,
                username="ADMIN",
                email="a@b.c",
                salt=SALT,
                verifier=calculate_verifier("ADMIN", "pw", SALT),
                totp_secret=None,
            )
        )
    async with app.router.lifespan_context(app):
        pass
    # seeding is idempotent
    async with app.router.lifespan_context(app):
        pass
    admins = (await portal_db.execute(select(Admin))).scalars().all()
    assert [a.account_id for a in admins] == [9]
    assert admins[0].granted_by is None


async def test_admin_seeding_survives_acore_outage(settings):
    settings.admin_usernames = "ADMIN"
    settings.acore_auth_url = "mysql+asyncmy://nobody:x@127.0.0.1:1/none"
    app = create_app(settings)
    async with app.router.lifespan_context(app):  # must not raise
        pass
