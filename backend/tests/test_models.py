import pytest
from sqlalchemy import select

from app.db.base import Base, make_engine, make_sessionmaker, utcnow
from app.db.models import Admin, AuditLog, Invite, PortalSession


@pytest.fixture
async def db(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = make_sessionmaker(engine)
    async with maker() as session:
        yield session
    await engine.dispose()


async def test_invite_roundtrip(db):
    inv = Invite(email="a@b.c", token_hash="h" * 64, created_by=1, expires_at=utcnow())
    db.add(inv)
    await db.commit()
    row = (await db.execute(select(Invite))).scalar_one()
    assert row.email == "a@b.c"
    assert row.used_at is None and row.revoked_at is None and row.account_id is None


async def test_session_and_admin_and_audit(db):
    db.add(PortalSession(id="s" * 64, account_id=5, username="X", expires_at=utcnow()))
    db.add(Admin(account_id=5, username="X", granted_by=1))
    db.add(AuditLog(action="login.success", target="X", actor_account_id=5, detail={"ip": "1.2.3.4"}))
    await db.commit()
    sess = (await db.execute(select(PortalSession))).scalar_one()
    assert sess.pending_totp_secret is None
    log = (await db.execute(select(AuditLog))).scalar_one()
    assert log.detail == {"ip": "1.2.3.4"}
    assert log.at is not None


def test_utcnow_naive():
    assert utcnow().tzinfo is None
