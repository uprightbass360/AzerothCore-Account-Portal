"""Read-only access to acore_auth. SELECT only, tables account + account_banned only."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    LargeBinary,
    MetaData,
    SmallInteger,
    String,
    Table,
    func,
    literal,
    select,
)
from sqlalchemy.ext.asyncio import AsyncEngine

metadata = MetaData()

account = Table(
    "account",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(32)),
    Column("salt", LargeBinary(32)),
    Column("verifier", LargeBinary(32)),
    Column("email", String(255)),
    Column("totp_secret", LargeBinary(128)),
    Column("last_login", DateTime),
    Column("joindate", DateTime),
)

account_banned = Table(
    "account_banned",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("bandate", Integer, primary_key=True),
    Column("unbandate", Integer),
    Column("bannedby", String(50)),
    Column("banreason", String(255)),
    Column("active", SmallInteger),
)

_COLS = [
    account.c.id,
    account.c.username,
    account.c.email,
    account.c.salt,
    account.c.verifier,
    account.c.totp_secret,
    account.c.last_login,
    account.c.joindate,
]


@dataclass
class AccountRow:
    id: int
    username: str
    email: str | None
    salt: bytes
    verifier: bytes
    totp_secret: bytes | None
    last_login: datetime | None
    joindate: datetime | None


def _row(r) -> AccountRow:
    return AccountRow(
        id=r.id,
        username=r.username,
        email=r.email,
        salt=r.salt,
        verifier=r.verifier,
        totp_secret=r.totp_secret,
        last_login=r.last_login,
        joindate=r.joindate,
    )


class AcoreReader:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def _one(self, stmt) -> AccountRow | None:
        async with self._engine.connect() as conn:
            r = (await conn.execute(stmt)).first()
        return _row(r) if r else None

    async def get_account(self, username: str) -> AccountRow | None:
        return await self._one(
            select(*_COLS).where(func.upper(account.c.username) == username.upper())
        )

    async def get_by_id(self, account_id: int) -> AccountRow | None:
        return await self._one(select(*_COLS).where(account.c.id == account_id))

    async def username_exists(self, username: str) -> bool:
        return await self.get_account(username) is not None

    async def list_accounts(
        self,
        search: str = "",
        offset: int = 0,
        limit: int = 25,
        exclude_prefixes: list[str] | None = None,
    ) -> tuple[list[AccountRow], int]:
        base = select(*_COLS)
        count = select(func.count()).select_from(account)
        if search:
            cond = func.upper(account.c.username).like(f"%{search.upper()}%")
            base, count = base.where(cond), count.where(cond)
        for prefix in exclude_prefixes or []:
            cond = func.upper(account.c.username).notlike(f"{prefix.upper()}%")
            base, count = base.where(cond), count.where(cond)
        async with self._engine.connect() as conn:
            total = (await conn.execute(count)).scalar_one()
            rows = (
                await conn.execute(base.order_by(account.c.id).offset(offset).limit(limit))
            ).all()
        return [_row(r) for r in rows], total

    async def banned_ids(self, ids: list[int]) -> set[int]:
        if not ids:
            return set()
        stmt = select(account_banned.c.id).where(
            account_banned.c.id.in_(ids), account_banned.c.active == 1
        )
        async with self._engine.connect() as conn:
            return {r.id for r in (await conn.execute(stmt)).all()}

    async def is_banned(self, account_id: int) -> bool:
        return account_id in await self.banned_ids([account_id])

    async def ping(self) -> bool:
        async with self._engine.connect() as conn:
            await conn.execute(select(literal(1)))
        return True
