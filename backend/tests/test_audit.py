import pytest
from sqlalchemy import select

from app.db.base import Base, make_engine, make_sessionmaker
from app.db.models import AuditLog
from app.services.audit import record


@pytest.fixture
async def db(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with make_sessionmaker(engine)() as session:
        yield session
    await engine.dispose()


async def test_record(db):
    await record(db, "invite.sent", "a@b.c", actor_account_id=7, detail={"invite_id": 1})
    await db.commit()
    row = (await db.execute(select(AuditLog))).scalar_one()
    assert (row.action, row.target, row.actor_account_id, row.detail) == (
        "invite.sent", "a@b.c", 7, {"invite_id": 1})


async def test_record_minimal(db):
    await record(db, "login.failed", "GHOST")
    await db.commit()
    row = (await db.execute(select(AuditLog))).scalar_one()
    assert row.actor_account_id is None and row.detail is None
