import pytest

from app.db.base import make_engine
from app.services import acore
from app.services.acore import AcoreReader


async def insert_account(engine, id, username, email="u@e.c", totp=None):
    async with engine.begin() as conn:
        await conn.execute(
            acore.account.insert().values(
                id=id,
                username=username,
                email=email,
                salt=b"\x01" * 32,
                verifier=b"\x02" * 32,
                totp_secret=totp,
            )
        )


async def ban(engine, id, active=1):
    async with engine.begin() as conn:
        await conn.execute(
            acore.account_banned.insert().values(
                id=id, bandate=1, unbandate=0, bannedby="portal", banreason="r", active=active
            )
        )


@pytest.fixture
async def engine(tmp_path):
    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path}/acore.db")
    async with eng.begin() as conn:
        await conn.run_sync(acore.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def reader(engine):
    return AcoreReader(engine)


async def test_get_account_case_insensitive(engine, reader):
    await insert_account(engine, 1, "TESTUSER", totp=b"\x0a" * 10)
    row = await reader.get_account("testuser")
    assert row is not None and row.id == 1 and row.totp_secret == b"\x0a" * 10
    assert await reader.get_account("missing") is None
    assert (await reader.get_by_id(1)).username == "TESTUSER"
    assert await reader.get_by_id(99) is None


async def test_username_exists(engine, reader):
    await insert_account(engine, 1, "ALICE")
    assert await reader.username_exists("alice") is True
    assert await reader.username_exists("bob") is False


async def test_list_accounts_search_and_pagination(engine, reader):
    for i, name in enumerate(["ALPHA", "BETA", "ALPINE"], start=1):
        await insert_account(engine, i, name)
    rows, total = await reader.list_accounts(search="alp")
    assert total == 2 and [r.username for r in rows] == ["ALPHA", "ALPINE"]
    rows, total = await reader.list_accounts(offset=1, limit=1)
    assert total == 3 and [r.username for r in rows] == ["BETA"]


async def test_banned(engine, reader):
    await insert_account(engine, 1, "A")
    await insert_account(engine, 2, "B")
    await ban(engine, 1, active=1)
    await ban(engine, 2, active=0)
    assert await reader.banned_ids([1, 2]) == {1}
    assert await reader.banned_ids([]) == set()
    assert await reader.is_banned(1) is True
    assert await reader.is_banned(2) is False


async def test_ping(engine, reader):
    assert await reader.ping() is True
    await engine.dispose()


async def test_list_accounts_search_case_insensitive(engine, reader):
    # Test case-insensitive search: username stored as mixed-case should match lowercase search
    await insert_account(engine, 1, "MixedCase")
    await insert_account(engine, 2, "Other")
    rows, total = await reader.list_accounts(search="mixed")
    assert total == 1 and len(rows) == 1 and rows[0].username == "MixedCase"
