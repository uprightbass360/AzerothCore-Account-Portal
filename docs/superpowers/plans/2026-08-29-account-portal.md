# AzerothCore Account Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Invite-only registration and account self-service portal for an AzerothCore/RealmMaster server: SvelteKit 2 frontend, FastAPI backend, account writes via SOAP, reads via read-only MySQL, app state in SQLite.

**Architecture:** Two docker services in this repo (`frontend` exposed, `backend` internal). The backend joins the RealmMaster docker network (external) to reach `ac-worldserver:7878` (SOAP) and `ac-mysql` (read-only). SvelteKit calls FastAPI only server-side; browser never touches FastAPI. Server-side sessions in SQLite; SRP6 login verified against `acore_auth`.

**Tech Stack:** Python 3.12+/uv, FastAPI 0.141, SQLAlchemy 2.0 async (aiosqlite + asyncmy), alembic, httpx (<1.0), respx, aiosmtplib, pyotp, segno, pydantic-settings, pytest 9 + pytest-asyncio (auto) + pytest-cov; SvelteKit 2 + Svelte 5 (runes), adapter-node, zod 4, Tailwind 4, vitest 4, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-29-account-portal-design.md`

## Global Constraints

- Python `>=3.12`, managed with uv. Node 22 for frontend.
- Pins: `fastapi[standard]>=0.141`, `sqlalchemy>=2.0,<2.1`, `httpx>=0.28,<1.0`, `zod` v4, Tailwind v4 via `@tailwindcss/vite`.
- **100% test coverage enforced**: backend `--cov=app --cov-fail-under=100` (branch coverage); frontend vitest thresholds 100 over `src/lib/**`, `src/**/*.server.ts`, `src/hooks.server.ts`. Playwright e2e excluded from coverage.
- All DB access is async (`create_async_engine`); sync SQLAlchemy inside `async def` is forbidden.
- `acore_auth` is SELECT-only, tables `account` and `account_banned` only. All writes go through SOAP.
- SOAP commands: `account create`, `account set password`, `account set 2fa`, `account set email`, `ban account`, `unban account`, `server info`. TOTP secrets are 16-char base32 (10 random bytes); DB stores decoded raw bytes.
- Every SOAP call: 5s timeout, one retry, failures surface as HTTP 503 "Game server temporarily unavailable".
- Env config only, prefix `PORTAL_` (backend). No secrets in code or logs; never log TOTP secrets or invite tokens.
- Backend working dir for all backend commands: `backend/`. Frontend: `frontend/`.
- Commit after every green test cycle. Conventional commit messages (`feat:`, `test:`, `chore:`, `docs:`).

## File Structure

```
backend/
├── pyproject.toml
├── alembic.ini            # + alembic/ (async template, versions/)
├── app/
│   ├── __init__.py
│   ├── main.py            # create_app factory, lifespan (admin seeding), error handlers
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py      # Settings (pydantic-settings, PORTAL_ prefix)
│   │   ├── srp6.py        # AzerothCore SRP6 verifier calc + verify
│   │   ├── security.py    # session token gen/hash, internal-key dependency
│   │   ├── ratelimit.py   # in-process token bucket
│   │   └── deps.py        # get_db/current_session/require_admin/service accessors
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py        # Base, engine/sessionmaker factories, utcnow
│   │   └── models.py      # Invite, PortalSession, Admin, AuditLog
│   ├── services/
│   │   ├── __init__.py
│   │   ├── audit.py       # record()
│   │   ├── acore.py       # read-only acore_auth reader (SQLAlchemy Core)
│   │   ├── soap.py        # SoapClient + command helpers
│   │   ├── mailer.py      # invite email via aiosmtplib
│   │   └── totp.py        # secret gen, otpauth URI, QR SVG, verify
│   └── api/
│       ├── __init__.py
│       ├── health.py
│       ├── auth.py        # /auth/login, /auth/login/2fa, /auth/logout
│       ├── register.py    # /register/{token}...
│       ├── user.py        # /user, /user/password, /user/2fa/*
│       └── admin.py       # /admin/*
└── tests/                 # mirrors app/ layout; conftest.py builds test app

frontend/
├── src/
│   ├── app.css            # @import "tailwindcss" + @theme tokens
│   ├── hooks.server.ts    # session → locals.user, route guards
│   ├── lib/
│   │   ├── schemas.ts     # zod schemas shared by all form actions
│   │   ├── components/FieldErrors.svelte
│   │   └── server/
│   │       ├── api.ts     # backend fetch wrapper (internal key + bearer)
│   │       └── forms.ts   # parseForm(request, schema)
│   └── routes/
│       ├── +layout.server.ts / +layout.svelte / +page.server.ts
│       ├── login/  logout/  register/[token]/  account/
│       └── admin/ (+layout.server.ts guard, invites/ accounts/ admins/ audit/)
├── e2e/portal.spec.ts     # Playwright smoke (manual/CI-optional)
└── Dockerfile

docker-compose.yml, .env.template, README.md   # repo root
```

---

### Task 1: Backend scaffold + Settings

**Files:**
- Create: `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/core/__init__.py`, `backend/app/core/config.py`, `backend/tests/__init__.py`, `backend/tests/test_config.py`, `backend/.gitignore`

**Interfaces:**
- Produces: `app.core.config.Settings` (fields listed below), `get_settings()` (lru_cached). All later tasks consume `Settings` via these exact field names.

- [ ] **Step 1: Scaffold the project**

```bash
mkdir -p backend/app/core backend/tests
cd backend
uv init --no-workspace --python 3.12 --bare .
uv add "fastapi[standard]>=0.141" "sqlalchemy>=2.0,<2.1" "alembic>=1.19" "aiosqlite>=0.22" "asyncmy>=0.2.10" "httpx>=0.28,<1.0" "aiosmtplib>=5.1" "pyotp>=2.10" "segno>=1.6" "pydantic-settings>=2.15"
uv add --dev "pytest>=9" "pytest-cov>=7" "pytest-asyncio>=1.4" "respx>=0.23" ruff
```

Create empty `backend/app/__init__.py`, `backend/app/core/__init__.py`, `backend/tests/__init__.py`. `backend/.gitignore`:

```
__pycache__/
*.db
.coverage
.env
```

Append to `backend/pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
addopts = "--cov=app --cov-report=term-missing --cov-fail-under=100"

[tool.coverage.run]
branch = true
source = ["app"]

[tool.ruff]
line-length = 100
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_config.py`:

```python
from app.core.config import Settings, get_settings


def make_settings(**overrides) -> Settings:
    defaults = dict(_env_file=None)
    defaults.update(overrides)
    return Settings(**defaults)


def test_defaults():
    s = make_settings()
    assert s.database_url.startswith("sqlite+aiosqlite")
    assert s.soap_url == "http://ac-worldserver:7878/"
    assert s.invite_ttl_days == 7
    assert s.session_ttl_days == 7
    assert s.totp_issuer == "AzerothCore"


def test_env_prefix(monkeypatch):
    monkeypatch.setenv("PORTAL_SOAP_USER", "gmbot")
    monkeypatch.setenv("PORTAL_INVITE_TTL_DAYS", "3")
    s = make_settings()
    assert s.soap_user == "gmbot"
    assert s.invite_ttl_days == 3


def test_admin_username_list_parses_and_uppercases():
    s = make_settings(admin_usernames=" alice, bob ,")
    assert s.admin_username_list == ["ALICE", "BOB"]
    assert make_settings().admin_username_list == []


def test_get_settings_cached():
    assert get_settings() is get_settings()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_config.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.config'`

- [ ] **Step 4: Write the implementation**

`backend/app/core/config.py`:

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PORTAL_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./portal.db"
    acore_auth_url: str = "mysql+asyncmy://portal_ro:change-me@ac-mysql:3306/acore_auth"
    soap_url: str = "http://ac-worldserver:7878/"
    soap_user: str = ""
    soap_pass: str = ""
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = "noreply@example.com"
    smtp_starttls: bool = True
    internal_api_key: str = "change-me"
    public_base_url: str = "http://localhost:3000"
    invite_ttl_days: int = 7
    session_ttl_days: int = 7
    totp_issuer: str = "AzerothCore"
    admin_usernames: str = ""

    @property
    def admin_username_list(self) -> list[str]:
        return [u.strip().upper() for u in self.admin_usernames.split(",") if u.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/test_config.py -v --no-cov`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "feat(backend): scaffold uv project with Settings"
```

---

### Task 2: SRP6 verification

**Files:**
- Create: `backend/app/core/srp6.py`, `backend/tests/test_srp6.py`

**Interfaces:**
- Produces: `calculate_verifier(username: str, password: str, salt: bytes) -> bytes` (32 bytes little-endian), `verify_password(username: str, password: str, salt: bytes, verifier: bytes) -> bool` (constant-time).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_srp6.py` — vectors generated with AzerothCore's algorithm (g=7, N=0x894B…9BB7, `SHA1(salt ‖ SHA1(USER:PASS))`, little-endian):

```python
from app.core.srp6 import calculate_verifier, verify_password

SALT1 = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
VERIFIER1 = bytes.fromhex("388aa0fa07b5252db2f75c032b20fd11d63e417277a0e566cf79acf642ceb771")
SALT2 = bytes.fromhex("ff" * 32)
VERIFIER2 = bytes.fromhex("028d6648bce001ea3757f1422dc2830148a0fb9bef14b6c3e5b70a1e2871c61a")


def test_known_vectors():
    assert calculate_verifier("testuser", "testpass", SALT1) == VERIFIER1
    assert calculate_verifier("ADMIN", "s3cret!", SALT2) == VERIFIER2


def test_case_insensitive():
    assert calculate_verifier("TestUser", "TESTPASS", SALT1) == VERIFIER1


def test_verify_password():
    assert verify_password("testuser", "testpass", SALT1, VERIFIER1) is True
    assert verify_password("testuser", "wrong", SALT1, VERIFIER1) is False
    assert verify_password("other", "testpass", SALT1, VERIFIER1) is False


def test_verifier_is_32_bytes():
    assert len(calculate_verifier("a", "b", SALT1)) == 32
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_srp6.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

`backend/app/core/srp6.py`:

```python
"""AzerothCore SRP6 verifier calculation (WoW 3.3.5 auth scheme)."""

import hashlib
import hmac

_N = int("894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7", 16)
_G = 7


def calculate_verifier(username: str, password: str, salt: bytes) -> bytes:
    h1 = hashlib.sha1(f"{username.upper()}:{password.upper()}".encode()).digest()
    x = int.from_bytes(hashlib.sha1(salt + h1).digest(), "little")
    return pow(_G, x, _N).to_bytes(32, "little")


def verify_password(username: str, password: str, salt: bytes, verifier: bytes) -> bool:
    return hmac.compare_digest(calculate_verifier(username, password, salt), verifier)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/test_srp6.py -v --no-cov`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/srp6.py backend/tests/test_srp6.py
git commit -m "feat(backend): AzerothCore SRP6 verifier with known-good vectors"
```

---

### Task 3: SQLite models + alembic

**Files:**
- Create: `backend/app/db/__init__.py`, `backend/app/db/base.py`, `backend/app/db/models.py`, `backend/tests/test_models.py`, `backend/alembic.ini`, `backend/alembic/` (via `alembic init`)

**Interfaces:**
- Produces: `Base`, `make_engine(url) -> AsyncEngine`, `make_sessionmaker(engine) -> async_sessionmaker[AsyncSession]`, `utcnow() -> datetime` (naive UTC) from `app.db.base`; models `Invite`, `PortalSession` (table `sessions`, includes `pending_totp_secret`), `Admin`, `AuditLog` from `app.db.models` with the exact columns below.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_models.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_models.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

`backend/app/db/__init__.py`: empty. `backend/app/db/base.py`:

```python
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
```

`backend/app/db/models.py`:

```python
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    account_id: Mapped[int | None] = mapped_column(Integer, default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class PortalSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of raw token
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    username: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    ip: Mapped[str | None] = mapped_column(String(45), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(255), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    pending_totp_secret: Mapped[str | None] = mapped_column(String(32), default=None)


class Admin(Base):
    __tablename__ = "admins"

    account_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(32))
    granted_by: Mapped[int | None] = mapped_column(Integer, default=None)  # None = env seed
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor_account_id: Mapped[int | None] = mapped_column(Integer, default=None)
    action: Mapped[str] = mapped_column(String(32), index=True)
    target: Mapped[str] = mapped_column(String(255), default="")
    detail: Mapped[dict | None] = mapped_column(JSON, default=None)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/test_models.py -v --no-cov`
Expected: 3 passed

- [ ] **Step 5: Set up alembic (async template) + initial migration**

```bash
cd backend
uv run alembic init -t async alembic
```

In `backend/alembic.ini` set: `sqlalchemy.url =` (leave empty — env.py supplies it).
Replace the config section of `backend/alembic/env.py` — after the imports add:

```python
from app.core.config import get_settings
from app.db import models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata
```

(Keep the rest of the async template as generated.) Then:

```bash
PORTAL_DATABASE_URL="sqlite+aiosqlite:///./portal.db" uv run alembic revision --autogenerate -m "initial schema"
PORTAL_DATABASE_URL="sqlite+aiosqlite:///./portal.db" uv run alembic upgrade head
rm -f portal.db
```

Verify: the generated file in `backend/alembic/versions/` creates tables `invites`, `sessions`, `admins`, `audit_log`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db backend/tests/test_models.py backend/alembic.ini backend/alembic
git commit -m "feat(backend): app DB models and initial alembic migration"
```

---

### Task 4: Audit service + security primitives + rate limiter

**Files:**
- Create: `backend/app/services/__init__.py`, `backend/app/services/audit.py`, `backend/app/core/security.py`, `backend/app/core/ratelimit.py`, `backend/tests/test_audit.py`, `backend/tests/test_security.py`, `backend/tests/test_ratelimit.py`

**Interfaces:**
- Consumes: models from Task 3.
- Produces:
  - `app.services.audit.record(db: AsyncSession, action: str, target: str, actor_account_id: int | None = None, detail: dict | None = None) -> None` (adds to session; caller commits).
  - `app.core.security.new_session_token() -> tuple[str, str]` (raw, sha256-hex), `hash_token(raw: str) -> str`.
  - `app.core.ratelimit.RateLimiter(rate: float, capacity: int)` with `allow(key: str, now: float | None = None) -> bool`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_audit.py`:

```python
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
```

`backend/tests/test_security.py`:

```python
import hashlib

from app.core.security import hash_token, new_session_token


def test_new_session_token():
    raw, hashed = new_session_token()
    assert len(hashed) == 64
    assert hashed == hashlib.sha256(raw.encode()).hexdigest()
    assert len(raw) >= 43  # 256 bits urlsafe


def test_tokens_unique():
    assert new_session_token()[0] != new_session_token()[0]


def test_hash_token_matches():
    raw, hashed = new_session_token()
    assert hash_token(raw) == hashed
```

`backend/tests/test_ratelimit.py`:

```python
from app.core.ratelimit import RateLimiter


def test_burst_then_deny():
    rl = RateLimiter(rate=1.0, capacity=3)
    assert [rl.allow("k", now=0.0) for _ in range(3)] == [True, True, True]
    assert rl.allow("k", now=0.0) is False


def test_refill_over_time():
    rl = RateLimiter(rate=1.0, capacity=2)
    assert rl.allow("k", now=0.0) and rl.allow("k", now=0.0)
    assert rl.allow("k", now=0.5) is False
    assert rl.allow("k", now=1.1) is True


def test_keys_independent():
    rl = RateLimiter(rate=1.0, capacity=1)
    assert rl.allow("a", now=0.0) is True
    assert rl.allow("b", now=0.0) is True
    assert rl.allow("a", now=0.0) is False


def test_capacity_not_exceeded_by_long_idle():
    rl = RateLimiter(rate=1.0, capacity=2)
    rl.allow("k", now=0.0)
    assert [rl.allow("k", now=1000.0) for _ in range(3)] == [True, True, False]


def test_now_defaults_to_monotonic():
    rl = RateLimiter(rate=1000.0, capacity=1)
    assert rl.allow("k") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_audit.py tests/test_security.py tests/test_ratelimit.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementations**

`backend/app/services/__init__.py`: empty. `backend/app/services/audit.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


async def record(
    db: AsyncSession,
    action: str,
    target: str,
    actor_account_id: int | None = None,
    detail: dict | None = None,
) -> None:
    db.add(AuditLog(action=action, target=target, actor_account_id=actor_account_id, detail=detail))
```

`backend/app/core/security.py`:

```python
import hashlib
import secrets


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_session_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)
```

`backend/app/core/ratelimit.py`:

```python
import time


class RateLimiter:
    """In-process token bucket, keyed. Single-instance backend, so no shared store."""

    def __init__(self, rate: float, capacity: int) -> None:
        self.rate = rate
        self.capacity = capacity
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last)

    def allow(self, key: str, now: float | None = None) -> bool:
        if now is None:
            now = time.monotonic()
        tokens, last = self._buckets.get(key, (float(self.capacity), now))
        tokens = min(self.capacity, tokens + (now - last) * self.rate)
        allowed = tokens >= 1.0
        if allowed:
            tokens -= 1.0
        self._buckets[key] = (tokens, now)
        return allowed
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/test_audit.py tests/test_security.py tests/test_ratelimit.py -v --no-cov`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services backend/app/core/security.py backend/app/core/ratelimit.py backend/tests
git commit -m "feat(backend): audit service, session tokens, rate limiter"
```

---

### Task 5: acore_auth reader (read-only)

**Files:**
- Create: `backend/app/services/acore.py`, `backend/tests/test_acore.py`

**Interfaces:**
- Consumes: `make_engine` from Task 3.
- Produces (`app.services.acore`):
  - `metadata: MetaData` with Core tables `account`, `account_banned` (used by tests to create a stub schema).
  - `@dataclass AccountRow: id: int; username: str; email: str | None; salt: bytes; verifier: bytes; totp_secret: bytes | None; last_login: datetime | None; joindate: datetime | None`
  - `class AcoreReader(engine)` with: `get_account(username) -> AccountRow | None` (case-insensitive), `get_by_id(account_id) -> AccountRow | None`, `username_exists(username) -> bool`, `list_accounts(search: str = "", offset: int = 0, limit: int = 25) -> tuple[list[AccountRow], int]` (ordered by id), `banned_ids(ids: list[int]) -> set[int]` (active bans only), `is_banned(account_id) -> bool`, `ping() -> bool`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_acore.py`:

```python
import pytest

from app.db.base import make_engine
from app.services import acore
from app.services.acore import AcoreReader


async def insert_account(engine, id, username, email="u@e.c", totp=None):
    async with engine.begin() as conn:
        await conn.execute(acore.account.insert().values(
            id=id, username=username, email=email,
            salt=b"\x01" * 32, verifier=b"\x02" * 32, totp_secret=totp))


async def ban(engine, id, active=1):
    async with engine.begin() as conn:
        await conn.execute(acore.account_banned.insert().values(
            id=id, bandate=1, unbandate=0, bannedby="portal", banreason="r", active=active))


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_acore.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

`backend/app/services/acore.py`:

```python
"""Read-only access to acore_auth. SELECT only, tables account + account_banned only."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (Column, DateTime, Integer, LargeBinary, MetaData, SmallInteger, String,
                        Table, func, literal, select)
from sqlalchemy.ext.asyncio import AsyncEngine

metadata = MetaData()

account = Table(
    "account", metadata,
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
    "account_banned", metadata,
    Column("id", Integer, primary_key=True),
    Column("bandate", Integer, primary_key=True),
    Column("unbandate", Integer),
    Column("bannedby", String(50)),
    Column("banreason", String(255)),
    Column("active", SmallInteger),
)

_COLS = [account.c.id, account.c.username, account.c.email, account.c.salt,
         account.c.verifier, account.c.totp_secret, account.c.last_login, account.c.joindate]


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
    return AccountRow(id=r.id, username=r.username, email=r.email, salt=r.salt,
                      verifier=r.verifier, totp_secret=r.totp_secret,
                      last_login=r.last_login, joindate=r.joindate)


class AcoreReader:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def _one(self, stmt) -> AccountRow | None:
        async with self._engine.connect() as conn:
            r = (await conn.execute(stmt)).first()
        return _row(r) if r else None

    async def get_account(self, username: str) -> AccountRow | None:
        return await self._one(select(*_COLS).where(
            func.upper(account.c.username) == username.upper()))

    async def get_by_id(self, account_id: int) -> AccountRow | None:
        return await self._one(select(*_COLS).where(account.c.id == account_id))

    async def username_exists(self, username: str) -> bool:
        return await self.get_account(username) is not None

    async def list_accounts(self, search: str = "", offset: int = 0,
                            limit: int = 25) -> tuple[list[AccountRow], int]:
        base = select(*_COLS)
        count = select(func.count()).select_from(account)
        if search:
            cond = account.c.username.like(f"%{search.upper()}%")
            base, count = base.where(cond), count.where(cond)
        async with self._engine.connect() as conn:
            total = (await conn.execute(count)).scalar_one()
            rows = (await conn.execute(base.order_by(account.c.id).offset(offset).limit(limit))).all()
        return [_row(r) for r in rows], total

    async def banned_ids(self, ids: list[int]) -> set[int]:
        if not ids:
            return set()
        stmt = select(account_banned.c.id).where(
            account_banned.c.id.in_(ids), account_banned.c.active == 1)
        async with self._engine.connect() as conn:
            return {r.id for r in (await conn.execute(stmt)).all()}

    async def is_banned(self, account_id: int) -> bool:
        return account_id in await self.banned_ids([account_id])

    async def ping(self) -> bool:
        async with self._engine.connect() as conn:
            await conn.execute(select(literal(1)))
        return True
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/test_acore.py -v --no-cov`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/acore.py backend/tests/test_acore.py
git commit -m "feat(backend): read-only acore_auth reader"
```

---

### Task 6: SOAP client

**Files:**
- Create: `backend/app/services/soap.py`, `backend/tests/test_soap.py`

**Interfaces:**
- Consumes: nothing internal.
- Produces (`app.services.soap`):
  - `class SoapError(Exception)` with `.message`.
  - `class SoapClient(url: str, username: str, password: str, timeout: float = 5.0)` with `execute(command: str) -> str` (result text; raises `SoapError` on fault or transport failure after 1 retry) and helpers: `account_create(username, password)`, `set_password(username, password)`, `set_email(username, email)`, `set_2fa(username, secret)`, `disable_2fa(username)`, `ban(username, reason)`, `unban(username)`, `server_info()` — each returning the result string.
- NOTE for implementer: `disable_2fa` sends `account set 2fa {username} off` and `set_email` sends `account set email {username} {email} {email}`. Before wiring the real stack (Task 19), verify both against the worldserver (`server info` works, then `help account set`); if this AC build lacks `account set email`, make `set_email` a no-op returning `""` and keep the portal-side email only (spec allows this fallback).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_soap.py`:

```python
import httpx
import pytest
import respx

from app.services.soap import SoapClient, SoapError

URL = "http://soap.test/"


def ok(result: str) -> httpx.Response:
    return httpx.Response(200, text=(
        '<?xml version="1.0"?><SOAP-ENV:Envelope '
        'xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="urn:AC">'
        f"<SOAP-ENV:Body><ns1:executeCommandResponse><result>{result}</result>"
        "</ns1:executeCommandResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>"))


def fault(msg: str) -> httpx.Response:
    return httpx.Response(500, text=(
        '<?xml version="1.0"?><SOAP-ENV:Envelope '
        'xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
        "<SOAP-ENV:Body><SOAP-ENV:Fault><faultcode>SOAP-ENV:Client</faultcode>"
        f"<faultstring>{msg}</faultstring></SOAP-ENV:Fault></SOAP-ENV:Body></SOAP-ENV:Envelope>"))


@pytest.fixture
def client():
    return SoapClient(URL, "gm", "pw")


@respx.mock
async def test_execute_success_sends_auth_and_command(client):
    route = respx.post(URL).mock(return_value=ok("Account created: BOB"))
    result = await client.execute("account create BOB pw")
    assert result == "Account created: BOB"
    req = route.calls.last.request
    assert b"account create BOB pw" in req.content
    assert req.headers["Authorization"].startswith("Basic ")
    assert "text/xml" in req.headers["Content-Type"]


@respx.mock
async def test_execute_fault_raises(client):
    respx.post(URL).mock(return_value=fault("Account already exist!"))
    with pytest.raises(SoapError) as e:
        await client.execute("account create BOB pw")
    assert "exist" in e.value.message


@respx.mock
async def test_transport_error_retries_once_then_raises(client):
    route = respx.post(URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(SoapError):
        await client.execute("server info")
    assert route.call_count == 2


@respx.mock
async def test_transport_error_then_success(client):
    route = respx.post(URL)
    route.side_effect = [httpx.ConnectError("blip"), ok("ok")]
    assert await client.execute("server info") == "ok"


@respx.mock
async def test_command_is_xml_escaped(client):
    route = respx.post(URL).mock(return_value=ok("x"))
    await client.execute("a <b> & 'c'")
    assert b"a &lt;b&gt; &amp;" in route.calls.last.request.content


@respx.mock
async def test_unparseable_response_raises(client):
    respx.post(URL).mock(return_value=httpx.Response(200, text="not xml"))
    with pytest.raises(SoapError):
        await client.execute("server info")


@respx.mock
async def test_helpers_build_commands(client):
    route = respx.post(URL).mock(return_value=ok("done"))
    await client.account_create("BOB", "pw12345678")
    assert b"account create BOB pw12345678" in route.calls.last.request.content
    await client.set_password("BOB", "newpw123")
    assert b"account set password BOB newpw123 newpw123" in route.calls.last.request.content
    await client.set_email("BOB", "b@c.d")
    assert b"account set email BOB b@c.d b@c.d" in route.calls.last.request.content
    await client.set_2fa("BOB", "ABCDEFGHIJKLMNOP")
    assert b"account set 2fa BOB ABCDEFGHIJKLMNOP" in route.calls.last.request.content
    await client.disable_2fa("BOB")
    assert b"account set 2fa BOB off" in route.calls.last.request.content
    await client.ban("BOB", "Locked via portal")
    assert b"ban account BOB -1 Locked via portal" in route.calls.last.request.content
    await client.unban("BOB")
    assert b"unban account BOB" in route.calls.last.request.content
    await client.server_info()
    assert b"server info" in route.calls.last.request.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_soap.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

`backend/app/services/soap.py`:

```python
"""AzerothCore SOAP client (urn:AC executeCommand)."""

import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import httpx

_ENVELOPE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
    'xmlns:ns1="urn:AC"><SOAP-ENV:Body><ns1:executeCommand><command>{command}</command>'
    "</ns1:executeCommand></SOAP-ENV:Body></SOAP-ENV:Envelope>"
)


class SoapError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _extract(text: str) -> str:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SoapError(f"unparseable SOAP response: {exc}") from exc
    fault = root.find(".//faultstring")
    if fault is not None:
        raise SoapError(fault.text or "SOAP fault")
    result = root.find(".//result")
    return (result.text or "") if result is not None else ""


class SoapClient:
    def __init__(self, url: str, username: str, password: str, timeout: float = 5.0) -> None:
        self._url = url
        self._auth = (username, password)
        self._timeout = timeout

    async def execute(self, command: str) -> str:
        body = _ENVELOPE.format(command=escape(command))
        last_exc: Exception | None = None
        for _ in range(2):  # one retry on transport errors
            try:
                async with httpx.AsyncClient(auth=self._auth, timeout=self._timeout) as client:
                    resp = await client.post(
                        self._url, content=body, headers={"Content-Type": "text/xml"})
                return _extract(resp.text)
            except httpx.HTTPError as exc:
                last_exc = exc
        raise SoapError(f"SOAP transport failure: {last_exc}")

    async def account_create(self, username: str, password: str) -> str:
        return await self.execute(f"account create {username} {password}")

    async def set_password(self, username: str, password: str) -> str:
        return await self.execute(f"account set password {username} {password} {password}")

    async def set_email(self, username: str, email: str) -> str:
        return await self.execute(f"account set email {username} {email} {email}")

    async def set_2fa(self, username: str, secret: str) -> str:
        return await self.execute(f"account set 2fa {username} {secret}")

    async def disable_2fa(self, username: str) -> str:
        return await self.execute(f"account set 2fa {username} off")

    async def ban(self, username: str, reason: str) -> str:
        return await self.execute(f"ban account {username} -1 {reason}")

    async def unban(self, username: str) -> str:
        return await self.execute(f"unban account {username}")

    async def server_info(self) -> str:
        return await self.execute("server info")
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/test_soap.py -v --no-cov`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/soap.py backend/tests/test_soap.py
git commit -m "feat(backend): AzerothCore SOAP client with retry and fault handling"
```

---

### Task 7: Mailer + TOTP service

**Files:**
- Create: `backend/app/services/mailer.py`, `backend/app/services/totp.py`, `backend/tests/test_mailer.py`, `backend/tests/test_totp.py`

**Interfaces:**
- Consumes: `Settings` (Task 1).
- Produces:
  - `app.services.mailer.Mailer(settings)` with `send_invite(to_email: str, link: str, expires_days: int) -> None` (raises `MailerError` on failure) and `ping() -> bool`.
  - `app.services.totp`: `new_secret() -> str` (16-char base32 from 10 random bytes — AC SOAP requirement), `provisioning_uri(secret, username, issuer) -> str`, `qr_svg(uri) -> str` (inline SVG via segno), `verify_code(secret: str, code: str) -> bool` (pyotp, `valid_window=1`), `secret_from_db(raw: bytes) -> str` (b32-encode DB's decoded bytes back to the pyotp form).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_totp.py`:

```python
import base64
import re

import pyotp

from app.services import totp


def test_new_secret_is_16_char_base32():
    s = totp.new_secret()
    assert re.fullmatch(r"[A-Z2-7]{16}", s)
    assert totp.new_secret() != s


def test_provisioning_uri():
    uri = totp.provisioning_uri("ABCDEFGHIJKLMNOP", "BOB", "MyRealm")
    assert uri.startswith("otpauth://totp/")
    assert "MyRealm" in uri and "BOB" in uri and "secret=ABCDEFGHIJKLMNOP" in uri


def test_qr_svg():
    svg = totp.qr_svg("otpauth://totp/x?secret=ABCDEFGHIJKLMNOP")
    assert svg.startswith("<svg") and "</svg>" in svg


def test_verify_code_window():
    s = totp.new_secret()
    assert totp.verify_code(s, pyotp.TOTP(s).now()) is True
    assert totp.verify_code(s, "000000") in (True, False)  # deterministic call, no crash
    assert totp.verify_code(s, "not6dig") is False


def test_secret_from_db_roundtrip():
    s = totp.new_secret()
    raw = base64.b32decode(s)
    assert totp.secret_from_db(raw) == s
```

`backend/tests/test_mailer.py`:

```python
from email.message import EmailMessage
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.services.mailer import Mailer, MailerError


@pytest.fixture
def mailer():
    return Mailer(Settings(_env_file=None, smtp_host="mail.test", smtp_port=587,
                           smtp_user="u", smtp_pass="p", smtp_from="noreply@t.co",
                           public_base_url="http://portal.test"))


async def test_send_invite(mailer):
    with patch("app.services.mailer.aiosmtplib.send", new_callable=AsyncMock) as send:
        await mailer.send_invite("new@player.com", "http://portal.test/register/tok", 7)
    msg = send.call_args.args[0]
    assert isinstance(msg, EmailMessage)
    assert msg["To"] == "new@player.com" and msg["From"] == "noreply@t.co"
    assert "http://portal.test/register/tok" in msg.get_body(("plain",)).get_content()
    assert "http://portal.test/register/tok" in msg.get_body(("html",)).get_content()
    kw = send.call_args.kwargs
    assert kw["hostname"] == "mail.test" and kw["port"] == 587
    assert kw["username"] == "u" and kw["password"] == "p" and kw["start_tls"] is True


async def test_send_invite_no_auth_when_no_user(mailer):
    mailer._settings.smtp_user = ""
    with patch("app.services.mailer.aiosmtplib.send", new_callable=AsyncMock) as send:
        await mailer.send_invite("a@b.c", "l", 7)
    kw = send.call_args.kwargs
    assert kw["username"] is None and kw["password"] is None


async def test_send_failure_raises(mailer):
    with patch("app.services.mailer.aiosmtplib.send", new_callable=AsyncMock,
               side_effect=OSError("refused")):
        with pytest.raises(MailerError):
            await mailer.send_invite("a@b.c", "l", 7)


async def test_ping(mailer):
    with patch("app.services.mailer.aiosmtplib.SMTP") as smtp_cls:
        inst = smtp_cls.return_value
        inst.connect = AsyncMock()
        inst.quit = AsyncMock()
        assert await mailer.ping() is True
    with patch("app.services.mailer.aiosmtplib.SMTP") as smtp_cls:
        smtp_cls.return_value.connect = AsyncMock(side_effect=OSError("down"))
        assert await mailer.ping() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_totp.py tests/test_mailer.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementations**

`backend/app/services/totp.py`:

```python
import base64
import os

import pyotp
import segno


def new_secret() -> str:
    """16-char base32 secret (10 random bytes) — AzerothCore SOAP requires exactly 16 chars."""
    return base64.b32encode(os.urandom(10)).decode("ascii")


def provisioning_uri(secret: str, username: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def qr_svg(uri: str) -> str:
    return segno.make(uri).svg_inline(scale=4)


def verify_code(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def secret_from_db(raw: bytes) -> str:
    """acore_auth stores the base32-DECODED bytes; pyotp wants base32 text."""
    return base64.b32encode(raw).decode("ascii")
```

`backend/app/services/mailer.py`:

```python
from email.message import EmailMessage

import aiosmtplib

from app.core.config import Settings


class MailerError(Exception):
    pass


class Mailer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send_invite(self, to_email: str, link: str, expires_days: int) -> None:
        s = self._settings
        msg = EmailMessage()
        msg["From"] = s.smtp_from
        msg["To"] = to_email
        msg["Subject"] = f"You're invited to join {s.totp_issuer}"
        text = (f"You've been invited to create a game account on {s.totp_issuer}.\n\n"
                f"Register here: {link}\n\n"
                f"This invite expires in {expires_days} days.")
        msg.set_content(text)
        msg.add_alternative(
            f"<p>You've been invited to create a game account on <b>{s.totp_issuer}</b>.</p>"
            f'<p><a href="{link}">Create your account</a></p>'
            f"<p>This invite expires in {expires_days} days.</p>", subtype="html")
        try:
            await aiosmtplib.send(
                msg, hostname=s.smtp_host, port=s.smtp_port,
                username=s.smtp_user or None, password=s.smtp_pass or None,
                start_tls=s.smtp_starttls)
        except (aiosmtplib.errors.SMTPException, OSError) as exc:
            raise MailerError(f"failed to send invite: {exc}") from exc

    async def ping(self) -> bool:
        s = self._settings
        try:
            client = aiosmtplib.SMTP(hostname=s.smtp_host, port=s.smtp_port)
            await client.connect(timeout=5)
            await client.quit()
            return True
        except (aiosmtplib.errors.SMTPException, OSError):
            return False
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/test_totp.py tests/test_mailer.py -v --no-cov`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/totp.py backend/app/services/mailer.py backend/tests
git commit -m "feat(backend): TOTP helpers and SMTP invite mailer"
```

---

### Task 8: App factory, dependencies, health endpoint, test harness

**Files:**
- Create: `backend/app/core/deps.py`, `backend/app/api/__init__.py`, `backend/app/api/health.py`, `backend/app/main.py`, `backend/tests/conftest.py`, `backend/tests/test_app.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces:
  - `app.main.create_app(settings: Settings | None = None) -> FastAPI` — wires on `app.state`: `settings`, `engine`, `sessionmaker`, `acore_engine`, `reader` (AcoreReader), `soap` (SoapClient), `mailer` (Mailer), `login_limiter` (RateLimiter(rate=0.2, capacity=5)). Lifespan seeds admins from `settings.admin_username_list` and disposes engines on shutdown. `SoapError` → 503 `{"detail": "Game server temporarily unavailable"}`.
  - `app.core.deps`: `get_db` (yields AsyncSession, per-request), `get_reader`, `get_soap`, `get_mailer`, `require_internal_key` (checks `X-Internal-Key` header, constant-time), `current_session -> PortalSession` (Bearer token; 401 if missing/expired/revoked; sliding renewal), `require_admin -> PortalSession` (403 if not in admins).
  - `tests/conftest.py` fixtures used by ALL router tests: `settings`, `app`, `client` (AsyncClient with `X-Internal-Key: test-key`, lifespan entered), `seed_account(id, username, password="testpass", email="u@e.c", totp_raw=None)`, `portal_db(app)` (AsyncSession into the portal DB), `login(client)` helper returning a bearer token.
  - Routes mounted in this task: `GET /api/v1/health` only (auth/register/user/admin routers are added by Tasks 9–12 — `create_app` includes them from the start, so this task creates those modules as empty routers: `router = APIRouter(prefix="/api/v1/...")` in each of `app/api/auth.py`, `app/api/register.py`, `app/api/user.py`, `app/api/admin.py`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/conftest.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.srp6 import calculate_verifier
from app.db.base import Base, make_engine, make_sessionmaker
from app.main import create_app
from app.services import acore

SALT = bytes(range(32))


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path}/portal.db",
        acore_auth_url=f"sqlite+aiosqlite:///{tmp_path}/acore.db",
        internal_api_key="test-key",
        soap_url="http://soap.test/",
        soap_user="gm",
        soap_pass="pw",
        public_base_url="http://portal.test",
        totp_issuer="TestRealm",
    )


async def _create_schemas(settings: Settings) -> None:
    eng = make_engine(settings.database_url)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await eng.dispose()
    eng = make_engine(settings.acore_auth_url)
    async with eng.begin() as conn:
        await conn.run_sync(acore.metadata.create_all)
    await eng.dispose()


@pytest.fixture
async def app(settings):
    await _create_schemas(settings)
    return create_app(settings)


@pytest.fixture
async def client(app):
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test",
                               headers={"X-Internal-Key": "test-key"}) as c:
            yield c


@pytest.fixture
def seed_account(app):
    async def _seed(id: int, username: str, password: str = "testpass",
                    email: str = "u@e.c", totp_raw: bytes | None = None) -> None:
        async with app.state.acore_engine.begin() as conn:
            await conn.execute(acore.account.insert().values(
                id=id, username=username.upper(), email=email, salt=SALT,
                verifier=calculate_verifier(username, password, SALT), totp_secret=totp_raw))
    return _seed


@pytest.fixture
async def portal_db(app):
    maker = make_sessionmaker(app.state.engine)
    async with maker() as session:
        yield session


@pytest.fixture
def login(client):
    async def _login(username: str = "testuser", password: str = "testpass") -> str:
        resp = await client.post("/api/v1/auth/login",
                                 json={"username": username, "password": password})
        assert resp.status_code == 200, resp.text
        return resp.json()["token"]
    return _login
```

`backend/tests/test_app.py`:

```python
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
    resp = await client.post("/api/v1/auth/login", headers={"X-Internal-Key": "wrong"},
                             json={"username": "a", "password": "b"})
    assert resp.status_code == 401


async def test_admin_seeding(settings, seed_account, portal_db):
    from tests.conftest import _create_schemas
    await _create_schemas(settings)
    settings.admin_usernames = "ADMIN,GHOST"
    app = create_app(settings)
    async with app.state.acore_engine.begin() as conn:
        from app.services import acore
        from app.core.srp6 import calculate_verifier
        from tests.conftest import SALT
        await conn.execute(acore.account.insert().values(
            id=9, username="ADMIN", email="a@b.c", salt=SALT,
            verifier=calculate_verifier("ADMIN", "pw", SALT), totp_secret=None))
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
```

NOTE: `test_health_acore_down` monkeypatches internals; if the implementation makes that awkward, instead point `settings.acore_auth_url` at a missing MySQL host and build a separate app. The behavior under test is: reader failure → `"acore_auth": "error"`, `status: "degraded"`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_app.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Write the implementation**

`backend/app/api/__init__.py`: empty. Stub routers so `create_app` can include them now — `backend/app/api/auth.py`:

```python
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
```

Same shape for `backend/app/api/register.py` (`prefix="/api/v1/register"`), `backend/app/api/user.py` (`prefix="/api/v1/user"`), `backend/app/api/admin.py` (`prefix="/api/v1/admin"`).

`backend/app/core/deps.py`:

```python
import hmac
from datetime import timedelta

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_token
from app.db.base import utcnow
from app.db.models import Admin, PortalSession
from app.services.acore import AcoreReader
from app.services.mailer import Mailer
from app.services.soap import SoapClient


async def get_db(request: Request):
    async with request.app.state.sessionmaker() as session:
        yield session


def get_reader(request: Request) -> AcoreReader:
    return request.app.state.reader


def get_soap(request: Request) -> SoapClient:
    return request.app.state.soap


def get_mailer(request: Request) -> Mailer:
    return request.app.state.mailer


async def require_internal_key(request: Request,
                               x_internal_key: str = Header(default="")) -> None:
    expected = request.app.state.settings.internal_api_key
    if not hmac.compare_digest(x_internal_key, expected):
        raise HTTPException(status_code=401, detail="Invalid internal API key")


async def current_session(request: Request,
                          db: AsyncSession = Depends(get_db),
                          authorization: str = Header(default="")) -> PortalSession:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    sess = await db.get(PortalSession, hash_token(authorization[7:]))
    now = utcnow()
    if sess is None or sess.revoked_at is not None or sess.expires_at < now:
        raise HTTPException(status_code=401, detail="Session expired")
    sess.expires_at = now + timedelta(days=request.app.state.settings.session_ttl_days)
    await db.commit()
    return sess


async def require_admin(sess: PortalSession = Depends(current_session),
                        db: AsyncSession = Depends(get_db)) -> PortalSession:
    if await db.get(Admin, sess.account_id) is None:
        raise HTTPException(status_code=403, detail="Admin access required")
    return sess
```

`backend/app/api/health.py`:

```python
from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/api/v1/health")
async def health(request: Request) -> dict:
    checks: dict[str, str] = {}
    try:
        await request.app.state.reader.ping()
        checks["acore_auth"] = "ok"
    except Exception:
        checks["acore_auth"] = "error"
    try:
        await request.app.state.soap.server_info()
        checks["soap"] = "ok"
    except Exception:
        checks["soap"] = "error"
    checks["smtp"] = "ok" if await request.app.state.mailer.ping() else "warn"
    degraded = checks["acore_auth"] == "error" or checks["soap"] == "error"
    return {"status": "degraded" if degraded else "ok", "checks": checks}
```

`backend/app/main.py`:

```python
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import admin, auth, health, register, user
from app.core.config import Settings, get_settings
from app.core.deps import require_internal_key
from app.core.ratelimit import RateLimiter
from app.db.base import make_engine, make_sessionmaker
from app.db.models import Admin
from app.services.acore import AcoreReader
from app.services.mailer import Mailer
from app.services.soap import SoapClient, SoapError

logger = logging.getLogger("portal")


async def seed_admins(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    if not settings.admin_username_list:
        return
    try:
        async with app.state.sessionmaker() as db:
            for name in settings.admin_username_list:
                acct = await app.state.reader.get_account(name)
                if acct is None:
                    logger.warning("admin seed: no acore account named %s", name)
                    continue
                if await db.get(Admin, acct.id) is None:
                    db.add(Admin(account_id=acct.id, username=acct.username, granted_by=None))
            await db.commit()
    except Exception:
        logger.warning("admin seeding failed (acore_auth unreachable?)", exc_info=True)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await seed_admins(app)
        yield
        await app.state.engine.dispose()
        await app.state.acore_engine.dispose()

    app = FastAPI(title="AzerothCore Account Portal", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    app.state.acore_engine = make_engine(settings.acore_auth_url)
    app.state.reader = AcoreReader(app.state.acore_engine)
    app.state.soap = SoapClient(settings.soap_url, settings.soap_user, settings.soap_pass)
    app.state.mailer = Mailer(settings)
    app.state.login_limiter = RateLimiter(rate=0.2, capacity=5)

    guarded = [Depends(require_internal_key)]
    app.include_router(health.router)
    app.include_router(auth.router, dependencies=guarded)
    app.include_router(register.router, dependencies=guarded)
    app.include_router(user.router, dependencies=guarded)
    app.include_router(admin.router, dependencies=guarded)

    @app.exception_handler(SoapError)
    async def soap_error_handler(request: Request, exc: SoapError) -> JSONResponse:
        logger.error("SOAP failure: %s", exc.message)
        return JSONResponse(status_code=503,
                            content={"detail": "Game server temporarily unavailable"})

    return app
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/test_app.py -v --no-cov`
Expected: 7 passed (adjust the two awkward health tests per the NOTE in Step 1 if implementation details differ — behavior, not mechanism, is the requirement)

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(backend): app factory, health endpoint, auth dependencies, test harness"
```

---

### Task 9: Auth router (login / 2FA / logout)

**Files:**
- Modify: `backend/app/api/auth.py` (replace stub)
- Create: `backend/tests/test_auth_api.py`

**Interfaces:**
- Consumes: conftest fixtures (Task 8), `verify_password` (Task 2), `new_session_token` (Task 4), `totp.verify_code`/`totp.secret_from_db` (Task 7), `audit.record` (Task 4), deps (Task 8).
- Produces HTTP contract consumed by the frontend (Task 14+):
  - `POST /api/v1/auth/login` `{username, password}` → 200 `{"token", "expires_at"}` | 200 `{"status": "2fa_required"}` | 401 `{"detail": "Invalid username or password"}` | 429.
  - `POST /api/v1/auth/login/2fa` `{username, password, code}` → 200 token | 401 (bad creds) | 401 `{"detail": "Invalid code"}`.
  - `POST /api/v1/auth/logout` (Bearer) → 200 `{"ok": true}`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_auth_api.py`:

```python
import base64

import pyotp
from sqlalchemy import select

from app.db.models import AuditLog, PortalSession


async def test_login_success(client, seed_account, portal_db):
    await seed_account(1, "testuser")
    resp = await client.post("/api/v1/auth/login",
                             json={"username": "TestUser", "password": "testpass"})
    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body and "expires_at" in body
    sess = (await portal_db.execute(select(PortalSession))).scalar_one()
    assert sess.account_id == 1 and sess.username == "TESTUSER"
    log = (await portal_db.execute(select(AuditLog))).scalar_one()
    assert log.action == "login.success"


async def test_login_wrong_password_and_unknown_user(client, seed_account, portal_db):
    await seed_account(1, "testuser")
    for creds in ({"username": "testuser", "password": "nope-nope"},
                  {"username": "ghost", "password": "whatever1"}):
        resp = await client.post("/api/v1/auth/login", json=creds)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid username or password"
    logs = (await portal_db.execute(select(AuditLog))).scalars().all()
    assert [l.action for l in logs] == ["login.failed", "login.failed"]


async def test_login_banned_account_generic_failure(client, seed_account, app):
    await seed_account(1, "testuser")
    from app.services import acore
    async with app.state.acore_engine.begin() as conn:
        await conn.execute(acore.account_banned.insert().values(
            id=1, bandate=1, unbandate=0, bannedby="portal", banreason="r", active=1))
    resp = await client.post("/api/v1/auth/login",
                             json={"username": "testuser", "password": "testpass"})
    assert resp.status_code == 401


async def test_login_2fa_flow(client, seed_account):
    secret_raw = b"\x0a" * 10
    await seed_account(1, "testuser", totp_raw=secret_raw)
    resp = await client.post("/api/v1/auth/login",
                             json={"username": "testuser", "password": "testpass"})
    assert resp.status_code == 200 and resp.json() == {"status": "2fa_required"}
    secret = base64.b32encode(secret_raw).decode()
    good = pyotp.TOTP(secret).now()
    resp = await client.post("/api/v1/auth/login/2fa",
                             json={"username": "testuser", "password": "testpass",
                                   "code": good})
    assert resp.status_code == 200 and "token" in resp.json()


async def test_login_2fa_wrong_code_and_wrong_password(client, seed_account):
    await seed_account(1, "testuser", totp_raw=b"\x0a" * 10)
    resp = await client.post("/api/v1/auth/login/2fa",
                             json={"username": "testuser", "password": "testpass",
                                   "code": "000001"})
    assert resp.status_code == 401 and resp.json()["detail"] == "Invalid code"
    resp = await client.post("/api/v1/auth/login/2fa",
                             json={"username": "testuser", "password": "wrongpw12",
                                   "code": "000001"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


async def test_login_rate_limited(client, seed_account):
    await seed_account(1, "testuser")
    for _ in range(5):
        await client.post("/api/v1/auth/login",
                          json={"username": "testuser", "password": "badbadbad"})
    resp = await client.post("/api/v1/auth/login",
                             json={"username": "testuser", "password": "testpass"})
    assert resp.status_code == 429


async def test_logout(client, seed_account, login, portal_db):
    await seed_account(1, "testuser")
    token = await login()
    resp = await client.post("/api/v1/auth/logout",
                             headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200 and resp.json() == {"ok": True}
    sess = (await portal_db.execute(select(PortalSession))).scalar_one()
    assert sess.revoked_at is not None
    resp = await client.post("/api/v1/auth/logout",
                             headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_logout_requires_bearer(client):
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 401
    resp = await client.post("/api/v1/auth/logout",
                             headers={"Authorization": "Bearer bogus"})
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_auth_api.py -v --no-cov`
Expected: FAIL — routes return 404/405 (stub router has no endpoints)

- [ ] **Step 3: Write the implementation**

Replace `backend/app/api/auth.py`:

```python
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import current_session, get_db, get_reader
from app.core.security import new_session_token
from app.core.srp6 import verify_password
from app.db.base import utcnow
from app.db.models import PortalSession
from app.services import totp
from app.services.acore import AccountRow, AcoreReader
from app.services.audit import record

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class TwoFaIn(LoginIn):
    code: str


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _checked_account(body: LoginIn, request: Request, db: AsyncSession,
                           reader: AcoreReader) -> AccountRow:
    ip = _client_ip(request)
    limiter = request.app.state.login_limiter
    if not (limiter.allow(f"ip:{ip}") and limiter.allow(f"user:{body.username.upper()}")):
        raise HTTPException(status_code=429, detail="Too many attempts, try again later")
    acct = await reader.get_account(body.username)
    ok = (acct is not None
          and not await reader.is_banned(acct.id)
          and verify_password(body.username, body.password, acct.salt, acct.verifier))
    if not ok:
        await record(db, "login.failed", body.username.upper(), detail={"ip": ip})
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return acct


async def _issue(request: Request, db: AsyncSession, acct: AccountRow) -> dict:
    settings = request.app.state.settings
    raw, hashed = new_session_token()
    sess = PortalSession(
        id=hashed, account_id=acct.id, username=acct.username,
        expires_at=utcnow() + timedelta(days=settings.session_ttl_days),
        ip=_client_ip(request), user_agent=request.headers.get("user-agent"))
    db.add(sess)
    await record(db, "login.success", acct.username, actor_account_id=acct.id,
                 detail={"ip": sess.ip})
    await db.commit()
    return {"token": raw, "expires_at": sess.expires_at.isoformat()}


@router.post("/login")
async def login(body: LoginIn, request: Request, db: AsyncSession = Depends(get_db),
                reader: AcoreReader = Depends(get_reader)) -> dict:
    acct = await _checked_account(body, request, db, reader)
    if acct.totp_secret:
        return {"status": "2fa_required"}
    return await _issue(request, db, acct)


@router.post("/login/2fa")
async def login_2fa(body: TwoFaIn, request: Request, db: AsyncSession = Depends(get_db),
                    reader: AcoreReader = Depends(get_reader)) -> dict:
    acct = await _checked_account(body, request, db, reader)
    if not acct.totp_secret or not totp.verify_code(
            totp.secret_from_db(acct.totp_secret), body.code):
        await record(db, "login.failed", acct.username, detail={"reason": "2fa"})
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid code")
    return await _issue(request, db, acct)


@router.post("/logout")
async def logout(sess: PortalSession = Depends(current_session),
                 db: AsyncSession = Depends(get_db)) -> dict:
    sess.revoked_at = utcnow()
    await db.commit()
    return {"ok": True}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/test_auth_api.py -v --no-cov`
Expected: 8 passed

- [ ] **Step 5: Run the full backend suite with coverage**

Run: `cd backend && uv run pytest`
Expected: all pass. Coverage will NOT be 100% yet (stub routers pending) — if `--cov-fail-under` blocks, run with `--no-cov` until Task 12, then enforce.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/auth.py backend/tests/test_auth_api.py
git commit -m "feat(backend): login with SRP6 + TOTP second step, logout"
```

---

### Task 10: Register router

**Files:**
- Modify: `backend/app/api/register.py` (replace stub)
- Create: `backend/tests/test_register_api.py`

**Interfaces:**
- Consumes: conftest (Task 8), `hash_token` (Task 4), SoapClient helpers (Task 6), models (Task 3).
- Produces HTTP contract:
  - `GET /api/v1/register/{token}` → 200 `{"email"}` | 404 `{"detail": "Invite not found"}` | 410 `{"detail": "Invite expired"}` / `"Invite already used or revoked"`.
  - `GET /api/v1/register/{token}/check-username?username=X` → 200 `{"valid": bool, "available": bool}`.
  - `POST /api/v1/register/{token}` `{username, password}` → 201 `{"username"}` | 404/410 (invite) | 409 `{"detail": "Username already taken"}` | 422 `{"detail": "Invalid username"| "Invalid password"}` | 503 (SOAP down).
  - Exports `USERNAME_RE` (`^[A-Za-z0-9]{3,20}$`) and `PASSWORD_RE` (`^[\x21-\x7e]{8,16}$`) reused by Task 12's user router.
- Test helper produced for later tasks: `tests/test_register_api.py::make_invite` is defined in conftest instead — add `invite` factory fixture to `backend/tests/conftest.py` (shown below).

- [ ] **Step 1: Add the invite factory to conftest**

Append to `backend/tests/conftest.py`:

```python
from datetime import timedelta

from app.core.security import new_session_token
from app.db.base import utcnow
from app.db.models import Invite


@pytest.fixture
def make_invite(app):
    async def _make(email: str = "new@player.com", days: int = 7,
                    used: bool = False, revoked: bool = False,
                    created_by: int = 99) -> tuple[str, int]:
        raw, hashed = new_session_token()
        maker = make_sessionmaker(app.state.engine)
        async with maker() as db:
            inv = Invite(email=email, token_hash=hashed, created_by=created_by,
                         expires_at=utcnow() + timedelta(days=days),
                         used_at=utcnow() if used else None,
                         revoked_at=utcnow() if revoked else None)
            db.add(inv)
            await db.commit()
            return raw, inv.id
    return _make
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_register_api.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_register_api.py -v --no-cov`
Expected: FAIL — 404s from stub router

- [ ] **Step 4: Write the implementation**

Replace `backend/app/api/register.py`:

```python
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_reader, get_soap
from app.core.security import hash_token
from app.db.base import utcnow
from app.db.models import Invite
from app.services.acore import AcoreReader
from app.services.audit import record
from app.services.soap import SoapClient, SoapError

router = APIRouter(prefix="/api/v1/register", tags=["register"])

USERNAME_RE = re.compile(r"^[A-Za-z0-9]{3,20}$")
PASSWORD_RE = re.compile(r"^[\x21-\x7e]{8,16}$")


class RegisterIn(BaseModel):
    username: str
    password: str


async def _valid_invite(token: str, db: AsyncSession) -> Invite:
    stmt = select(Invite).where(Invite.token_hash == hash_token(token))
    inv = (await db.execute(stmt)).scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    if inv.used_at is not None or inv.revoked_at is not None:
        raise HTTPException(status_code=410, detail="Invite already used or revoked")
    if inv.expires_at < utcnow():
        raise HTTPException(status_code=410, detail="Invite expired")
    return inv


@router.get("/{token}")
async def invite_info(token: str, db: AsyncSession = Depends(get_db)) -> dict:
    inv = await _valid_invite(token, db)
    return {"email": inv.email}


@router.get("/{token}/check-username")
async def check_username(token: str, username: str,
                         db: AsyncSession = Depends(get_db),
                         reader: AcoreReader = Depends(get_reader)) -> dict:
    await _valid_invite(token, db)
    if not USERNAME_RE.fullmatch(username):
        return {"valid": False, "available": False}
    return {"valid": True, "available": not await reader.username_exists(username)}


@router.post("/{token}", status_code=201)
async def register(token: str, body: RegisterIn,
                   db: AsyncSession = Depends(get_db),
                   reader: AcoreReader = Depends(get_reader),
                   soap: SoapClient = Depends(get_soap)) -> dict:
    inv = await _valid_invite(token, db)
    if not USERNAME_RE.fullmatch(body.username):
        raise HTTPException(status_code=422, detail="Invalid username")
    if not PASSWORD_RE.fullmatch(body.password):
        raise HTTPException(status_code=422, detail="Invalid password")
    username = body.username.upper()
    if await reader.username_exists(username):
        raise HTTPException(status_code=409, detail="Username already taken")

    try:
        await soap.account_create(username, body.password)
    except SoapError as exc:
        if "exist" in exc.message.lower():
            raise HTTPException(status_code=409, detail="Username already taken") from exc
        raise  # global handler → 503

    email_set = True
    try:
        await soap.set_email(username, inv.email)
    except SoapError:
        email_set = False

    acct = await reader.get_account(username)
    inv.used_at = utcnow()
    inv.account_id = acct.id if acct else None
    await record(db, "invite.redeemed", inv.email, detail={"invite_id": inv.id})
    await record(db, "account.created", username, detail={"email_set": email_set})
    await db.commit()
    return {"username": username}
```

- [ ] **Step 5: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/test_register_api.py -v --no-cov`
Expected: 9 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/register.py backend/tests
git commit -m "feat(backend): invite validation and registration via SOAP"
```

---

### Task 11: User router (profile, password, 2FA)

**Files:**
- Modify: `backend/app/api/user.py` (replace stub)
- Create: `backend/tests/test_user_api.py`

**Interfaces:**
- Consumes: conftest + `login` fixture (Task 8/9), `PASSWORD_RE` (Task 10), totp service (Task 7), SoapClient (Task 6).
- Produces HTTP contract:
  - `GET /api/v1/user` (Bearer) → `{"username", "email", "totp_enabled", "is_admin"}`.
  - `POST /api/v1/user/password` `{current_password, new_password}` → 200 `{"ok": true}` | 403 wrong current | 422 invalid new; revokes all OTHER sessions.
  - `POST /api/v1/user/2fa/setup` → 200 `{"secret", "otpauth_uri", "qr_svg"}` | 409 if already enabled; stores secret on THIS session row (`pending_totp_secret`).
  - `POST /api/v1/user/2fa/confirm` `{code}` → 200 | 400 `"No 2FA setup in progress"` | 400 `"Invalid code"`; calls SOAP `set_2fa`.
  - `POST /api/v1/user/2fa/disable` `{password, code}` → 200 | 400/403; calls SOAP `disable_2fa`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_user_api.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_user_api.py -v --no-cov`
Expected: FAIL — 404s from stub router

- [ ] **Step 3: Write the implementation**

Replace `backend/app/api/user.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.register import PASSWORD_RE
from app.core.deps import current_session, get_db, get_reader, get_soap
from app.core.srp6 import verify_password
from app.db.base import utcnow
from app.db.models import Admin, PortalSession
from app.services import totp
from app.services.acore import AccountRow, AcoreReader
from app.services.audit import record
from app.services.soap import SoapClient

router = APIRouter(prefix="/api/v1/user", tags=["user"])


class PasswordIn(BaseModel):
    current_password: str
    new_password: str


class CodeIn(BaseModel):
    code: str


class DisableIn(BaseModel):
    password: str
    code: str


async def _account(sess: PortalSession, reader: AcoreReader) -> AccountRow:
    acct = await reader.get_by_id(sess.account_id)
    if acct is None:
        raise HTTPException(status_code=401, detail="Account no longer exists")
    return acct


@router.get("")
async def get_user(sess: PortalSession = Depends(current_session),
                   db: AsyncSession = Depends(get_db),
                   reader: AcoreReader = Depends(get_reader)) -> dict:
    acct = await _account(sess, reader)
    return {"username": acct.username, "email": acct.email,
            "totp_enabled": bool(acct.totp_secret),
            "is_admin": await db.get(Admin, sess.account_id) is not None}


@router.post("/password")
async def change_password(body: PasswordIn,
                          sess: PortalSession = Depends(current_session),
                          db: AsyncSession = Depends(get_db),
                          reader: AcoreReader = Depends(get_reader),
                          soap: SoapClient = Depends(get_soap)) -> dict:
    acct = await _account(sess, reader)
    if not verify_password(acct.username, body.current_password, acct.salt, acct.verifier):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    if not PASSWORD_RE.fullmatch(body.new_password):
        raise HTTPException(status_code=422, detail="Invalid password")
    await soap.set_password(acct.username, body.new_password)
    await db.execute(update(PortalSession)
                     .where(PortalSession.account_id == sess.account_id,
                            PortalSession.id != sess.id,
                            PortalSession.revoked_at.is_(None))
                     .values(revoked_at=utcnow()))
    await record(db, "password.changed", acct.username, actor_account_id=acct.id)
    await db.commit()
    return {"ok": True}


@router.post("/2fa/setup")
async def twofa_setup(request: Request,
                      sess: PortalSession = Depends(current_session),
                      db: AsyncSession = Depends(get_db),
                      reader: AcoreReader = Depends(get_reader)) -> dict:
    acct = await _account(sess, reader)
    if acct.totp_secret:
        raise HTTPException(status_code=409, detail="2FA already enabled")
    secret = totp.new_secret()
    sess.pending_totp_secret = secret
    await db.commit()
    uri = totp.provisioning_uri(secret, acct.username,
                                request.app.state.settings.totp_issuer)
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": totp.qr_svg(uri)}


@router.post("/2fa/confirm")
async def twofa_confirm(body: CodeIn,
                        sess: PortalSession = Depends(current_session),
                        db: AsyncSession = Depends(get_db),
                        reader: AcoreReader = Depends(get_reader),
                        soap: SoapClient = Depends(get_soap)) -> dict:
    acct = await _account(sess, reader)
    if not sess.pending_totp_secret:
        raise HTTPException(status_code=400, detail="No 2FA setup in progress")
    if not totp.verify_code(sess.pending_totp_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid code")
    await soap.set_2fa(acct.username, sess.pending_totp_secret)
    sess.pending_totp_secret = None
    await record(db, "2fa.enabled", acct.username, actor_account_id=acct.id)
    await db.commit()
    return {"ok": True}


@router.post("/2fa/disable")
async def twofa_disable(body: DisableIn,
                        sess: PortalSession = Depends(current_session),
                        db: AsyncSession = Depends(get_db),
                        reader: AcoreReader = Depends(get_reader),
                        soap: SoapClient = Depends(get_soap)) -> dict:
    acct = await _account(sess, reader)
    if not acct.totp_secret:
        raise HTTPException(status_code=400, detail="2FA is not enabled")
    if not verify_password(acct.username, body.password, acct.salt, acct.verifier):
        raise HTTPException(status_code=403, detail="Password is incorrect")
    if not totp.verify_code(totp.secret_from_db(acct.totp_secret), body.code):
        raise HTTPException(status_code=400, detail="Invalid code")
    await soap.disable_2fa(acct.username)
    await record(db, "2fa.disabled", acct.username, actor_account_id=acct.id)
    await db.commit()
    return {"ok": True}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/test_user_api.py -v --no-cov`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/user.py backend/tests/test_user_api.py
git commit -m "feat(backend): user profile, password change, 2FA self-service"
```

---

### Task 12: Admin router + full-coverage gate

**Files:**
- Modify: `backend/app/api/admin.py` (replace stub)
- Create: `backend/tests/test_admin_api.py`

**Interfaces:**
- Consumes: everything prior; `Mailer.send_invite`/`MailerError` (Task 7), `require_admin` (Task 8).
- Produces HTTP contract (all under Bearer of an admin session; non-admin → 403):
  - `POST /api/v1/admin/invites` `{email}` → 201 `{"id", "email", "expires_at"}` | 502 `{"detail": "Failed to send invite email"}`. Re-inviting an email revokes the previous pending invite.
  - `GET /api/v1/admin/invites` → `{"items": [{id, email, created_at, expires_at}]}` (pending only, newest first).
  - `DELETE /api/v1/admin/invites/{id}` → 200 | 404.
  - `GET /api/v1/admin/accounts?search=&page=1` → `{"items": [{id, username, email, joindate, last_login, totp_enabled, locked, is_admin, invited_email}], "total", "page", "pages"}` (25/page).
  - `POST /api/v1/admin/accounts/{username}/lock` → 200 (SOAP ban -1, revokes target's sessions) | 404 | 400 self-lock.
  - `POST /api/v1/admin/accounts/{username}/unlock` → 200 (SOAP unban) | 404.
  - `GET /api/v1/admin/admins` → `{"items": [{account_id, username, granted_by, granted_at}]}`.
  - `POST /api/v1/admin/admins` `{username}` → 201 | 404 `"No such game account"` | 409.
  - `DELETE /api/v1/admin/admins/{account_id}` → 200 | 404 | 400 `"Cannot remove the last admin"`.
  - `GET /api/v1/admin/audit?action=&page=1` → `{"items": [{at, actor_account_id, action, target, detail}], "total", "page", "pages"}` (50/page, newest first).

- [ ] **Step 1: Add an admin login helper to conftest**

Append to `backend/tests/conftest.py`:

```python
from app.db.models import Admin


@pytest.fixture
def admin_login(app, seed_account, login):
    async def _admin(id: int = 90, username: str = "boss") -> str:
        await seed_account(id, username)
        maker = make_sessionmaker(app.state.engine)
        async with maker() as db:
            if await db.get(Admin, id) is None:
                db.add(Admin(account_id=id, username=username.upper(), granted_by=None))
                await db.commit()
        return await login(username, "testpass")
    return _admin
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_admin_api.py`:

```python
from unittest.mock import AsyncMock, patch

import respx
from sqlalchemy import select

from app.db.models import Admin, Invite, PortalSession
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_admin_api.py -v --no-cov`
Expected: FAIL — 404s from stub router

- [ ] **Step 4: Write the implementation**

Replace `backend/app/api/admin.py`:

```python
import math
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_mailer, get_reader, get_soap, require_admin
from app.core.security import new_session_token
from app.db.base import utcnow
from app.db.models import Admin, AuditLog, Invite, PortalSession
from app.services.acore import AcoreReader
from app.services.audit import record
from app.services.mailer import Mailer, MailerError
from app.services.soap import SoapClient

router = APIRouter(prefix="/api/v1/admin", tags=["admin"],
                   dependencies=[Depends(require_admin)])

PAGE_SIZE = 25
AUDIT_PAGE_SIZE = 50


class InviteIn(BaseModel):
    email: EmailStr


class AdminIn(BaseModel):
    username: str


@router.post("/invites", status_code=201)
async def create_invite(body: InviteIn, request: Request,
                        sess: PortalSession = Depends(require_admin),
                        db: AsyncSession = Depends(get_db),
                        mailer: Mailer = Depends(get_mailer)) -> dict:
    settings = request.app.state.settings
    raw, hashed = new_session_token()
    link = f"{settings.public_base_url}/register/{raw}"
    try:
        await mailer.send_invite(body.email, link, settings.invite_ttl_days)
    except MailerError as exc:
        raise HTTPException(status_code=502, detail="Failed to send invite email") from exc

    replaced = await db.execute(
        update(Invite)
        .where(Invite.email == body.email, Invite.used_at.is_(None),
               Invite.revoked_at.is_(None))
        .values(revoked_at=utcnow()))
    if replaced.rowcount:
        await record(db, "invite.revoked", body.email,
                     actor_account_id=sess.account_id, detail={"reason": "replaced"})
    inv = Invite(email=body.email, token_hash=hashed, created_by=sess.account_id,
                 expires_at=utcnow() + timedelta(days=settings.invite_ttl_days))
    db.add(inv)
    await db.flush()
    await record(db, "invite.sent", body.email, actor_account_id=sess.account_id,
                 detail={"invite_id": inv.id})
    await db.commit()
    return {"id": inv.id, "email": inv.email, "expires_at": inv.expires_at.isoformat()}


@router.get("/invites")
async def list_invites(db: AsyncSession = Depends(get_db)) -> dict:
    stmt = (select(Invite)
            .where(Invite.used_at.is_(None), Invite.revoked_at.is_(None))
            .order_by(Invite.created_at.desc()))
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [{"id": i.id, "email": i.email,
                       "created_at": i.created_at.isoformat(),
                       "expires_at": i.expires_at.isoformat()} for i in rows]}


@router.delete("/invites/{invite_id}")
async def revoke_invite(invite_id: int,
                        sess: PortalSession = Depends(require_admin),
                        db: AsyncSession = Depends(get_db)) -> dict:
    inv = await db.get(Invite, invite_id)
    if inv is None or inv.used_at is not None or inv.revoked_at is not None:
        raise HTTPException(status_code=404, detail="Invite not found")
    inv.revoked_at = utcnow()
    await record(db, "invite.revoked", inv.email, actor_account_id=sess.account_id)
    await db.commit()
    return {"ok": True}


@router.get("/accounts")
async def list_accounts(search: str = "", page: int = 1,
                        db: AsyncSession = Depends(get_db),
                        reader: AcoreReader = Depends(get_reader)) -> dict:
    rows, total = await reader.list_accounts(search=search,
                                             offset=(page - 1) * PAGE_SIZE,
                                             limit=PAGE_SIZE)
    ids = [r.id for r in rows]
    banned = await reader.banned_ids(ids)
    admin_ids = set((await db.execute(
        select(Admin.account_id).where(Admin.account_id.in_(ids or [0])))).scalars())
    invites = {i.account_id: i.email for i in (await db.execute(
        select(Invite).where(Invite.account_id.in_(ids or [0])))).scalars()}
    items = [{
        "id": r.id, "username": r.username, "email": r.email,
        "joindate": r.joindate.isoformat() if r.joindate else None,
        "last_login": r.last_login.isoformat() if r.last_login else None,
        "totp_enabled": bool(r.totp_secret), "locked": r.id in banned,
        "is_admin": r.id in admin_ids, "invited_email": invites.get(r.id),
    } for r in rows]
    return {"items": items, "total": total, "page": page,
            "pages": max(1, math.ceil(total / PAGE_SIZE))}


@router.post("/accounts/{username}/lock")
async def lock_account(username: str,
                       sess: PortalSession = Depends(require_admin),
                       db: AsyncSession = Depends(get_db),
                       reader: AcoreReader = Depends(get_reader),
                       soap: SoapClient = Depends(get_soap)) -> dict:
    acct = await reader.get_account(username)
    if acct is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if acct.id == sess.account_id:
        raise HTTPException(status_code=400, detail="Cannot lock your own account")
    await soap.ban(acct.username, "Locked via portal")
    await db.execute(update(PortalSession)
                     .where(PortalSession.account_id == acct.id,
                            PortalSession.revoked_at.is_(None))
                     .values(revoked_at=utcnow()))
    await record(db, "account.locked", acct.username, actor_account_id=sess.account_id)
    await db.commit()
    return {"ok": True}


@router.post("/accounts/{username}/unlock")
async def unlock_account(username: str,
                         sess: PortalSession = Depends(require_admin),
                         db: AsyncSession = Depends(get_db),
                         reader: AcoreReader = Depends(get_reader),
                         soap: SoapClient = Depends(get_soap)) -> dict:
    acct = await reader.get_account(username)
    if acct is None:
        raise HTTPException(status_code=404, detail="Account not found")
    await soap.unban(acct.username)
    await record(db, "account.unlocked", acct.username, actor_account_id=sess.account_id)
    await db.commit()
    return {"ok": True}


@router.get("/admins")
async def list_admins(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(Admin).order_by(Admin.granted_at))).scalars().all()
    return {"items": [{"account_id": a.account_id, "username": a.username,
                       "granted_by": a.granted_by,
                       "granted_at": a.granted_at.isoformat()} for a in rows]}


@router.post("/admins", status_code=201)
async def grant_admin(body: AdminIn,
                      sess: PortalSession = Depends(require_admin),
                      db: AsyncSession = Depends(get_db),
                      reader: AcoreReader = Depends(get_reader)) -> dict:
    acct = await reader.get_account(body.username)
    if acct is None:
        raise HTTPException(status_code=404, detail="No such game account")
    if await db.get(Admin, acct.id) is not None:
        raise HTTPException(status_code=409, detail="Already an admin")
    db.add(Admin(account_id=acct.id, username=acct.username, granted_by=sess.account_id))
    await record(db, "admin.granted", acct.username, actor_account_id=sess.account_id)
    await db.commit()
    return {"account_id": acct.id, "username": acct.username}


@router.delete("/admins/{account_id}")
async def revoke_admin(account_id: int,
                       sess: PortalSession = Depends(require_admin),
                       db: AsyncSession = Depends(get_db)) -> dict:
    target = await db.get(Admin, account_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Not an admin")
    total = (await db.execute(select(func.count()).select_from(Admin))).scalar_one()
    if total <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the last admin")
    await db.delete(target)
    await record(db, "admin.revoked", target.username, actor_account_id=sess.account_id)
    await db.commit()
    return {"ok": True}


@router.get("/audit")
async def list_audit(action: str = "", page: int = 1,
                     db: AsyncSession = Depends(get_db)) -> dict:
    base = select(AuditLog)
    count = select(func.count()).select_from(AuditLog)
    if action:
        base, count = base.where(AuditLog.action == action), count.where(
            AuditLog.action == action)
    total = (await db.execute(count)).scalar_one()
    rows = (await db.execute(base.order_by(AuditLog.at.desc(), AuditLog.id.desc())
                             .offset((page - 1) * AUDIT_PAGE_SIZE)
                             .limit(AUDIT_PAGE_SIZE))).scalars().all()
    items = [{"at": r.at.isoformat(), "actor_account_id": r.actor_account_id,
              "action": r.action, "target": r.target, "detail": r.detail} for r in rows]
    return {"items": items, "total": total, "page": page,
            "pages": max(1, math.ceil(total / AUDIT_PAGE_SIZE))}
```

- [ ] **Step 5: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/test_admin_api.py -v --no-cov`
Expected: 9 passed

- [ ] **Step 6: Enforce the 100% coverage gate**

Run: `cd backend && uv run pytest`
Expected: ALL tests pass AND total coverage is 100% (the `--cov-fail-under=100` in pyproject now applies for good). If any line/branch is uncovered, add the missing test — do NOT add `# pragma: no cover` except for `if TYPE_CHECKING:` blocks. Then:

Run: `cd backend && uv run ruff check . && uv run ruff format --check .`
Expected: clean (fix or `ruff format` as needed).

- [ ] **Step 7: Commit**

```bash
git add backend
git commit -m "feat(backend): admin invites, accounts, admins, audit; 100% coverage gate"
```

---

### Task 13: Frontend scaffold + shared schemas + server helpers

**Files:**
- Create: `frontend/` (via `npx sv create`), `frontend/src/lib/schemas.ts`, `frontend/src/lib/server/forms.ts`, `frontend/src/lib/server/api.ts`, `frontend/src/app.d.ts` (edit), `frontend/src/lib/schemas.test.ts`, `frontend/src/lib/server/forms.test.ts`, `frontend/src/lib/server/api.test.ts`

**Interfaces:**
- Produces (consumed by every page task):
  - `$lib/schemas`: `loginSchema {username, password}`, `totpSchema {username, password, code}`, `registerSchema {username, password, confirm}` (cross-field match), `passwordChangeSchema {current_password, new_password, confirm}`, `inviteSchema {email}`, `grantAdminSchema {username}`, `codeSchema {code}`, `disable2faSchema {password, code}`.
  - `$lib/server/forms`: `parseForm(request, schema)` → `{ok: true, data}` | `{ok: false, errors: Record<string, string[]>, values: Record<string, string>}` (values redact any field whose name contains `password`, `confirm`, or `code`).
  - `$lib/server/api`: `api<T>(event, method, path, body?)` → `{status: number, data: T}` — adds `X-Internal-Key` from `env.INTERNAL_API_KEY`, `Authorization: Bearer` from the `session` cookie, JSON body; `setSessionCookie(event, token, expiresAt)` and `clearSessionCookie(event)` (cookie `session`, HttpOnly, SameSite=Lax, Path=/, Secure iff https).
  - `App.Locals` typed as `{ user: PortalUser | null }` with `PortalUser = {username: string; email: string | null; totp_enabled: boolean; is_admin: boolean}` (exported from `$lib/server/api`).

- [ ] **Step 1: Scaffold**

```bash
npx sv create frontend --template minimal --types ts --no-add-ons --no-install
cd frontend
npx sv add tailwindcss eslint prettier vitest --no-install
npm install
npm install -D @vitest/coverage-v8
npm install -D @sveltejs/adapter-node && npm uninstall @sveltejs/adapter-auto
```

Edit `frontend/svelte.config.js`: import `adapter from '@sveltejs/adapter-node'`.
Edit the vitest config the add-on generated (in `vite.config.ts`): set

```ts
test: {
  environment: 'node',
  include: ['src/**/*.{test,spec}.ts'],
  coverage: {
    provider: 'v8',
    include: ['src/lib/**/*.ts', 'src/**/*.server.ts', 'src/hooks.server.ts'],
    thresholds: { lines: 100, functions: 100, branches: 100, statements: 100 }
  }
}
```

(If the add-on generated a browser/client test project split, collapse it to this single node project — components are covered by Playwright, not vitest.)

Verify scaffold: `npm run build` succeeds; commit the raw scaffold before adding code:

```bash
git add frontend
git commit -m "chore(frontend): SvelteKit 2 scaffold with adapter-node, tailwind, vitest"
```

- [ ] **Step 2: Write the failing tests**

`frontend/src/lib/schemas.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import {
  disable2faSchema, grantAdminSchema, inviteSchema, loginSchema,
  passwordChangeSchema, registerSchema, totpSchema
} from './schemas';

describe('schemas', () => {
  it('loginSchema requires both fields', () => {
    expect(loginSchema.safeParse({ username: 'a', password: 'b' }).success).toBe(true);
    expect(loginSchema.safeParse({ username: '', password: 'b' }).success).toBe(false);
  });

  it('totpSchema requires 6 digits', () => {
    expect(totpSchema.safeParse({ username: 'a', password: 'b', code: '123456' }).success).toBe(true);
    expect(totpSchema.safeParse({ username: 'a', password: 'b', code: '12345' }).success).toBe(false);
  });

  it('registerSchema enforces AC constraints and confirm match', () => {
    const good = { username: 'Newbie1', password: 'hunter2!!', confirm: 'hunter2!!' };
    expect(registerSchema.safeParse(good).success).toBe(true);
    expect(registerSchema.safeParse({ ...good, username: 'x!' }).success).toBe(false);
    expect(registerSchema.safeParse({ ...good, password: 'short', confirm: 'short' }).success).toBe(false);
    expect(registerSchema.safeParse({ ...good, password: 'x'.repeat(17), confirm: 'x'.repeat(17) }).success).toBe(false);
    const mismatch = registerSchema.safeParse({ ...good, confirm: 'different1' });
    expect(mismatch.success).toBe(false);
  });

  it('passwordChangeSchema mirrors register rules', () => {
    const good = { current_password: 'old', new_password: 'hunter2!!', confirm: 'hunter2!!' };
    expect(passwordChangeSchema.safeParse(good).success).toBe(true);
    expect(passwordChangeSchema.safeParse({ ...good, confirm: 'nope-nope' }).success).toBe(false);
  });

  it('inviteSchema validates email', () => {
    expect(inviteSchema.safeParse({ email: 'a@b.co' }).success).toBe(true);
    expect(inviteSchema.safeParse({ email: 'nope' }).success).toBe(false);
  });

  it('grantAdminSchema and disable2faSchema', () => {
    expect(grantAdminSchema.safeParse({ username: 'Boss1' }).success).toBe(true);
    expect(grantAdminSchema.safeParse({ username: '!' }).success).toBe(false);
    expect(disable2faSchema.safeParse({ password: 'x', code: '123456' }).success).toBe(true);
    expect(disable2faSchema.safeParse({ password: '', code: '123456' }).success).toBe(false);
  });
});
```

`frontend/src/lib/server/forms.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { loginSchema, registerSchema } from '$lib/schemas';
import { parseForm } from './forms';

function req(fields: Record<string, string>): Request {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.set(k, v);
  return new Request('http://t.est', { method: 'POST', body: fd });
}

describe('parseForm', () => {
  it('returns data on valid input', async () => {
    const r = await parseForm(req({ username: 'a', password: 'b' }), loginSchema);
    expect(r).toEqual({ ok: true, data: { username: 'a', password: 'b' } });
  });

  it('returns field errors and redacts secrets', async () => {
    const r = await parseForm(
      req({ username: 'x!', password: 'secret99', confirm: 'other' }), registerSchema);
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.errors.username?.[0]).toBeTruthy();
      expect(r.values.username).toBe('x!');
      expect(r.values.password).toBeUndefined();
      expect(r.values.confirm).toBeUndefined();
    }
  });

  it('ignores non-string entries', async () => {
    const fd = new FormData();
    fd.set('username', 'a');
    fd.set('password', 'b');
    fd.set('file', new Blob(['x']));
    const r = await parseForm(
      new Request('http://t.est', { method: 'POST', body: fd }), loginSchema);
    expect(r.ok).toBe(true);
  });
});
```

`frontend/src/lib/server/api.test.ts`:

```ts
import { describe, expect, it, vi } from 'vitest';
import type { RequestEvent } from '@sveltejs/kit';

vi.mock('$env/dynamic/private', () => ({
  env: { BACKEND_URL: 'http://backend.test', INTERNAL_API_KEY: 'k3y' }
}));

import { api, clearSessionCookie, setSessionCookie } from './api';

function makeEvent(cookie?: string): RequestEvent & { fetchMock: ReturnType<typeof vi.fn> } {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ hello: 'world' }), { status: 200 }));
  return {
    fetch: fetchMock,
    fetchMock,
    url: new URL('https://portal.test/x'),
    cookies: {
      get: vi.fn().mockReturnValue(cookie),
      set: vi.fn(),
      delete: vi.fn()
    }
  } as unknown as RequestEvent & { fetchMock: ReturnType<typeof vi.fn> };
}

describe('api', () => {
  it('sends internal key, bearer, and json body', async () => {
    const event = makeEvent('tok123');
    const res = await api(event, 'POST', '/api/v1/auth/login', { a: 1 });
    expect(res).toEqual({ status: 200, data: { hello: 'world' } });
    const [url, init] = event.fetchMock.mock.calls[0];
    expect(url).toBe('http://backend.test/api/v1/auth/login');
    expect(init.headers['X-Internal-Key']).toBe('k3y');
    expect(init.headers['Authorization']).toBe('Bearer tok123');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(init.body).toBe(JSON.stringify({ a: 1 }));
  });

  it('omits bearer and body when absent', async () => {
    const event = makeEvent(undefined);
    await api(event, 'GET', '/api/v1/health');
    const [, init] = event.fetchMock.mock.calls[0];
    expect(init.headers['Authorization']).toBeUndefined();
    expect(init.body).toBeUndefined();
  });

  it('tolerates non-json responses', async () => {
    const event = makeEvent();
    event.fetchMock.mockResolvedValue(new Response('oops', { status: 502 }));
    const res = await api(event, 'GET', '/x');
    expect(res).toEqual({ status: 502, data: {} });
  });
});

describe('cookies', () => {
  it('sets and clears the session cookie', () => {
    const event = makeEvent();
    setSessionCookie(event, 'tok', '2027-01-01T00:00:00');
    expect(event.cookies.set).toHaveBeenCalledWith('session', 'tok', {
      path: '/', httpOnly: true, sameSite: 'lax', secure: true,
      expires: new Date('2027-01-01T00:00:00')
    });
    clearSessionCookie(event);
    expect(event.cookies.delete).toHaveBeenCalledWith('session', { path: '/' });
  });

  it('secure=false on http origins', () => {
    const event = makeEvent();
    (event as { url: URL }).url = new URL('http://localhost:3000/');
    setSessionCookie(event, 'tok', '2027-01-01T00:00:00');
    expect((event.cookies.set as ReturnType<typeof vi.fn>).mock.calls[0][2].secure).toBe(false);
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npx vitest run --coverage=false`
Expected: FAIL — modules not found

- [ ] **Step 4: Write the implementations**

`frontend/src/lib/schemas.ts`:

```ts
import { z } from 'zod';

const USERNAME = z.string().regex(/^[A-Za-z0-9]{3,20}$/, '3–20 letters or numbers');
const GAME_PASSWORD = z
  .string()
  .regex(/^[\x21-\x7e]{8,16}$/, '8–16 characters, no spaces');
const TOTP_CODE = z.string().regex(/^\d{6}$/, 'Enter the 6-digit code');

export const loginSchema = z.object({
  username: z.string().min(1, 'Username is required'),
  password: z.string().min(1, 'Password is required')
});

export const totpSchema = loginSchema.extend({ code: TOTP_CODE });

export const registerSchema = z
  .object({ username: USERNAME, password: GAME_PASSWORD, confirm: z.string() })
  .refine((d) => d.password === d.confirm, {
    message: 'Passwords do not match',
    path: ['confirm']
  });

export const passwordChangeSchema = z
  .object({
    current_password: z.string().min(1, 'Current password is required'),
    new_password: GAME_PASSWORD,
    confirm: z.string()
  })
  .refine((d) => d.new_password === d.confirm, {
    message: 'Passwords do not match',
    path: ['confirm']
  });

export const inviteSchema = z.object({ email: z.email('Enter a valid email address') });

export const grantAdminSchema = z.object({ username: USERNAME });

export const codeSchema = z.object({ code: TOTP_CODE });

export const disable2faSchema = z.object({
  password: z.string().min(1, 'Password is required'),
  code: TOTP_CODE
});
```

`frontend/src/lib/server/forms.ts`:

```ts
import { z, type ZodType } from 'zod';

export type FormFailure = {
  ok: false;
  errors: Record<string, string[]>;
  values: Record<string, string>;
};
export type FormResult<T> = { ok: true; data: T } | FormFailure;

const SECRET_FIELD = /password|confirm|code/i;

export async function parseForm<T>(request: Request, schema: ZodType<T>): Promise<FormResult<T>> {
  const fd = await request.formData();
  const raw: Record<string, string> = {};
  for (const [k, v] of fd.entries()) if (typeof v === 'string') raw[k] = v;
  const parsed = schema.safeParse(raw);
  if (parsed.success) return { ok: true, data: parsed.data };
  const { fieldErrors } = z.flattenError(parsed.error);
  const values: Record<string, string> = {};
  for (const [k, v] of Object.entries(raw)) if (!SECRET_FIELD.test(k)) values[k] = v;
  return { ok: false, errors: fieldErrors as Record<string, string[]>, values };
}
```

`frontend/src/lib/server/api.ts`:

```ts
import { env } from '$env/dynamic/private';
import type { RequestEvent } from '@sveltejs/kit';

export type PortalUser = {
  username: string;
  email: string | null;
  totp_enabled: boolean;
  is_admin: boolean;
};

export type ApiResponse<T> = { status: number; data: T };

export async function api<T = Record<string, unknown>>(
  event: RequestEvent,
  method: string,
  path: string,
  body?: unknown
): Promise<ApiResponse<T>> {
  const headers: Record<string, string> = { 'X-Internal-Key': env.INTERNAL_API_KEY ?? '' };
  const token = event.cookies.get('session');
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const init: RequestInit = { method, headers };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await event.fetch(`${env.BACKEND_URL}${path}`, init);
  const data = (await res.json().catch(() => ({}))) as T;
  return { status: res.status, data };
}

export function setSessionCookie(event: RequestEvent, token: string, expiresAt: string): void {
  event.cookies.set('session', token, {
    path: '/',
    httpOnly: true,
    sameSite: 'lax',
    secure: event.url.protocol === 'https:',
    expires: new Date(expiresAt)
  });
}

export function clearSessionCookie(event: RequestEvent): void {
  event.cookies.delete('session', { path: '/' });
}
```

`frontend/src/app.d.ts` — set the Locals interface:

```ts
import type { PortalUser } from '$lib/server/api';

declare global {
  namespace App {
    interface Locals {
      user: PortalUser | null;
    }
  }
}

export {};
```

- [ ] **Step 5: Run tests, verify pass**

Run: `cd frontend && npx vitest run --coverage=false`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat(frontend): zod schemas, form parser, backend api client"
```

---

### Task 14: Hooks, layout, login/logout

**Files:**
- Create: `frontend/src/hooks.server.ts`, `frontend/src/hooks.server.test.ts`, `frontend/src/lib/components/FieldErrors.svelte`, `frontend/src/routes/+layout.server.ts`, `frontend/src/routes/+layout.svelte`, `frontend/src/routes/+page.server.ts`, `frontend/src/routes/login/+page.server.ts`, `frontend/src/routes/login/+page.svelte`, `frontend/src/routes/login/page.server.test.ts`, `frontend/src/routes/logout/+page.server.ts`

**Interfaces:**
- Consumes: `api`, `setSessionCookie`, `clearSessionCookie`, `PortalUser` (Task 13), `loginSchema`/`totpSchema`, `parseForm`.
- Produces: `locals.user` populated for every request; guards: `/account*` and `/admin*` need login (303 → `/login`), `/admin*` additionally needs `is_admin` (303 → `/account`). Login action names: `login`, `twofa`. Logout: `POST /logout` (default action). `FieldErrors.svelte` props: `{ errors?: string[] }`.
- Test pattern produced here and reused by Tasks 15–17: mock `$lib/server/api` with `vi.mock`, build a fake `RequestEvent` with a `FormData` request, call the action, assert on `api` calls / returned `fail` / thrown redirect.

- [ ] **Step 1: Write the failing tests**

`frontend/src/hooks.server.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/server/api', async (orig) => {
  const mod = (await orig()) as object;
  return { ...mod, api: vi.fn(), clearSessionCookie: vi.fn() };
});
vi.mock('$env/dynamic/private', () => ({ env: { BACKEND_URL: 'http://b', INTERNAL_API_KEY: 'k' } }));

import { api, clearSessionCookie } from '$lib/server/api';
import { handle } from './hooks.server';

const USER = { username: 'BOB', email: null, totp_enabled: false, is_admin: false };

function makeEvent(path: string, cookie?: string) {
  return {
    url: new URL(`http://portal.test${path}`),
    cookies: { get: vi.fn().mockReturnValue(cookie), delete: vi.fn() },
    locals: {} as { user: unknown },
    fetch: vi.fn()
  };
}
const resolve = vi.fn().mockResolvedValue(new Response('ok'));

beforeEach(() => vi.clearAllMocks());

describe('handle', () => {
  it('no cookie → anonymous, public routes pass', async () => {
    const event = makeEvent('/login');
    await handle({ event, resolve } as never);
    expect(event.locals.user).toBeNull();
    expect(resolve).toHaveBeenCalled();
  });

  it('valid cookie → locals.user set', async () => {
    vi.mocked(api).mockResolvedValue({ status: 200, data: USER });
    const event = makeEvent('/account', 'tok');
    await handle({ event, resolve } as never);
    expect(event.locals.user).toEqual(USER);
  });

  it('stale cookie → cleared, guard redirects', async () => {
    vi.mocked(api).mockResolvedValue({ status: 401, data: {} });
    const event = makeEvent('/account', 'tok');
    await expect(handle({ event, resolve } as never)).rejects.toMatchObject({ status: 303, location: '/login' });
    expect(clearSessionCookie).toHaveBeenCalled();
  });

  it('non-admin on /admin → redirected to /account', async () => {
    vi.mocked(api).mockResolvedValue({ status: 200, data: USER });
    const event = makeEvent('/admin/invites', 'tok');
    await expect(handle({ event, resolve } as never)).rejects.toMatchObject({ status: 303, location: '/account' });
  });

  it('admin on /admin → passes', async () => {
    vi.mocked(api).mockResolvedValue({ status: 200, data: { ...USER, is_admin: true } });
    const event = makeEvent('/admin/invites', 'tok');
    await handle({ event, resolve } as never);
    expect(resolve).toHaveBeenCalled();
  });
});
```

`frontend/src/routes/login/page.server.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/server/api', async (orig) => {
  const mod = (await orig()) as object;
  return { ...mod, api: vi.fn(), setSessionCookie: vi.fn() };
});
vi.mock('$env/dynamic/private', () => ({ env: {} }));

import { api, setSessionCookie } from '$lib/server/api';
import { actions, load } from './+page.server';

function formEvent(fields: Record<string, string>, cookie?: string) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.set(k, v);
  return {
    request: new Request('http://t.est', { method: 'POST', body: fd }),
    cookies: { get: vi.fn().mockReturnValue(cookie), set: vi.fn(), delete: vi.fn() },
    url: new URL('http://t.est/login'),
    fetch: vi.fn(),
    locals: { user: null }
  } as never;
}

beforeEach(() => vi.clearAllMocks());

describe('load', () => {
  it('redirects logged-in users to /account', () => {
    try {
      load({ locals: { user: { username: 'X' } } } as never);
      expect.unreachable('should have redirected');
    } catch (e) {
      expect(e).toMatchObject({ status: 303, location: '/account' });
    }
    expect(load({ locals: { user: null } } as never)).toEqual({});
  });
});

describe('login action', () => {
  it('sets cookie and redirects on success', async () => {
    vi.mocked(api).mockResolvedValue({
      status: 200, data: { token: 't0k', expires_at: '2027-01-01T00:00:00' } });
    await expect(actions.login(formEvent({ username: 'bob', password: 'pw123456' })))
      .rejects.toMatchObject({ status: 303, location: '/account' });
    expect(setSessionCookie).toHaveBeenCalledWith(expect.anything(), 't0k', '2027-01-01T00:00:00');
  });

  it('returns twofa step when required', async () => {
    vi.mocked(api).mockResolvedValue({ status: 200, data: { status: '2fa_required' } });
    const res = await actions.login(formEvent({ username: 'bob', password: 'pw123456' }));
    expect(res).toEqual({ twofa: true, username: 'bob', password: 'pw123456' });
  });

  it('fails with message on 401 and 429', async () => {
    vi.mocked(api).mockResolvedValue({ status: 401, data: { detail: 'Invalid username or password' } });
    let res = await actions.login(formEvent({ username: 'bob', password: 'x1234567' }));
    expect(res).toMatchObject({ status: 401, data: { message: 'Invalid username or password' } });
    vi.mocked(api).mockResolvedValue({ status: 429, data: { detail: 'Too many attempts, try again later' } });
    res = await actions.login(formEvent({ username: 'bob', password: 'x1234567' }));
    expect(res).toMatchObject({ status: 429 });
  });

  it('fails on invalid form input without calling the api', async () => {
    const res = await actions.login(formEvent({ username: '', password: '' }));
    expect(res).toMatchObject({ status: 400 });
    expect(api).not.toHaveBeenCalled();
  });
});

describe('twofa action', () => {
  it('issues session on valid code', async () => {
    vi.mocked(api).mockResolvedValue({
      status: 200, data: { token: 't0k', expires_at: '2027-01-01T00:00:00' } });
    await expect(actions.twofa(formEvent({ username: 'bob', password: 'pw123456', code: '123456' })))
      .rejects.toMatchObject({ status: 303 });
  });

  it('keeps the twofa form on invalid code', async () => {
    vi.mocked(api).mockResolvedValue({ status: 401, data: { detail: 'Invalid code' } });
    const res = await actions.twofa(formEvent({ username: 'bob', password: 'pw123456', code: '111111' }));
    expect(res).toMatchObject({ status: 401, data: { twofa: true, message: 'Invalid code' } });
  });
});
```

Note on the `fail()` assertion shape: SvelteKit's `fail(status, data)` returns an `ActionFailure` with `.status` and `.data`. If the installed version exposes the payload differently, match on what `fail` actually returns — the tested behavior is status + message, not the object's internal shape.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run --coverage=false`
Expected: FAIL — `hooks.server` / `+page.server` not found

- [ ] **Step 3: Write the implementations**

`frontend/src/hooks.server.ts`:

```ts
import { redirect, type Handle } from '@sveltejs/kit';
import { api, clearSessionCookie, type PortalUser } from '$lib/server/api';

export const handle: Handle = async ({ event, resolve }) => {
  event.locals.user = null;
  if (event.cookies.get('session')) {
    const { status, data } = await api<PortalUser>(event, 'GET', '/api/v1/user');
    if (status === 200) event.locals.user = data;
    else clearSessionCookie(event);
  }
  const path = event.url.pathname;
  const needsAuth = path.startsWith('/account') || path.startsWith('/admin');
  if (needsAuth && !event.locals.user) redirect(303, '/login');
  if (path.startsWith('/admin') && !event.locals.user?.is_admin) redirect(303, '/account');
  return resolve(event);
};
```

`frontend/src/routes/+layout.server.ts`:

```ts
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = ({ locals }) => ({ user: locals.user });
```

`frontend/src/routes/+page.server.ts`:

```ts
import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = ({ locals }) => {
  redirect(303, locals.user ? '/account' : '/login');
};
```

`frontend/src/lib/components/FieldErrors.svelte`:

```svelte
<script lang="ts">
  let { errors }: { errors?: string[] } = $props();
</script>

{#if errors?.length}
  <p class="mt-1 text-sm text-red-600">{errors[0]}</p>
{/if}
```

`frontend/src/routes/+layout.svelte`:

```svelte
<script lang="ts">
  import '../app.css';
  let { data, children } = $props();
</script>

<div class="min-h-screen bg-stone-100 text-stone-900">
  <nav class="border-b border-stone-300 bg-stone-900 text-stone-100">
    <div class="mx-auto flex max-w-4xl items-center gap-6 px-4 py-3">
      <a href="/" class="font-semibold tracking-wide">Account Portal</a>
      <div class="ml-auto flex items-center gap-4 text-sm">
        {#if data.user}
          <a href="/account" class="hover:underline">{data.user.username}</a>
          {#if data.user.is_admin}<a href="/admin/invites" class="hover:underline">Admin</a>{/if}
          <form method="POST" action="/logout"><button class="hover:underline">Log out</button></form>
        {:else}
          <a href="/login" class="hover:underline">Log in</a>
        {/if}
      </div>
    </div>
  </nav>
  <main class="mx-auto max-w-4xl px-4 py-8">
    {@render children()}
  </main>
</div>
```

`frontend/src/routes/login/+page.server.ts`:

```ts
import { fail, redirect } from '@sveltejs/kit';
import { loginSchema, totpSchema } from '$lib/schemas';
import { api, setSessionCookie } from '$lib/server/api';
import { parseForm } from '$lib/server/forms';
import type { Actions, PageServerLoad } from './$types';

type LoginResponse = { token?: string; expires_at?: string; status?: string; detail?: string };

export const load: PageServerLoad = ({ locals }) => {
  if (locals.user) redirect(303, '/account');
  return {};
};

export const actions: Actions = {
  login: async (event) => {
    const parsed = await parseForm(event.request, loginSchema);
    if (!parsed.ok) return fail(400, parsed);
    const { status, data } = await api<LoginResponse>(
      event, 'POST', '/api/v1/auth/login', parsed.data);
    if (status === 200 && data.token) {
      setSessionCookie(event, data.token, data.expires_at!);
      redirect(303, '/account');
    }
    if (status === 200 && data.status === '2fa_required') {
      // password round-trips through the server-rendered 2FA form only, never to the browser log
      return { twofa: true, username: parsed.data.username, password: parsed.data.password };
    }
    return fail(status, {
      message: data.detail ?? 'Login failed',
      values: { username: parsed.data.username }
    });
  },

  twofa: async (event) => {
    const parsed = await parseForm(event.request, totpSchema);
    if (!parsed.ok) return fail(400, { ...parsed, twofa: true });
    const { status, data } = await api<LoginResponse>(
      event, 'POST', '/api/v1/auth/login/2fa', parsed.data);
    if (status === 200 && data.token) {
      setSessionCookie(event, data.token, data.expires_at!);
      redirect(303, '/account');
    }
    return fail(status, {
      twofa: true,
      username: parsed.data.username,
      password: parsed.data.password,
      message: data.detail ?? 'Login failed'
    });
  }
};
```

`frontend/src/routes/login/+page.svelte`:

```svelte
<script lang="ts">
  import { enhance } from '$app/forms';
  import FieldErrors from '$lib/components/FieldErrors.svelte';
  let { form } = $props();
</script>

<div class="mx-auto max-w-sm rounded border border-stone-300 bg-white p-6 shadow-sm">
  {#if form?.twofa}
    <h1 class="mb-4 text-lg font-semibold">Two-factor authentication</h1>
    <form method="POST" action="?/twofa" use:enhance>
      <input type="hidden" name="username" value={form.username} />
      <input type="hidden" name="password" value={form.password} />
      <label class="mb-1 block text-sm" for="code">6-digit code</label>
      <input id="code" name="code" inputmode="numeric" autocomplete="one-time-code"
        class="w-full rounded border border-stone-300 px-3 py-2" />
      <FieldErrors errors={form?.errors?.code} />
      {#if form?.message}<p class="mt-2 text-sm text-red-600">{form.message}</p>{/if}
      <button class="mt-4 w-full rounded bg-stone-900 py-2 text-stone-100">Verify</button>
    </form>
  {:else}
    <h1 class="mb-4 text-lg font-semibold">Log in</h1>
    <form method="POST" action="?/login" use:enhance>
      <label class="mb-1 block text-sm" for="username">Username</label>
      <input id="username" name="username" value={form?.values?.username ?? ''}
        class="w-full rounded border border-stone-300 px-3 py-2" />
      <FieldErrors errors={form?.errors?.username} />
      <label class="mb-1 mt-3 block text-sm" for="password">Password</label>
      <input id="password" name="password" type="password"
        class="w-full rounded border border-stone-300 px-3 py-2" />
      <FieldErrors errors={form?.errors?.password} />
      {#if form?.message}<p class="mt-2 text-sm text-red-600">{form.message}</p>{/if}
      <button class="mt-4 w-full rounded bg-stone-900 py-2 text-stone-100">Log in</button>
    </form>
  {/if}
</div>
```

`frontend/src/routes/logout/+page.server.ts`:

```ts
import { redirect } from '@sveltejs/kit';
import { api, clearSessionCookie } from '$lib/server/api';
import type { Actions } from './$types';

export const actions: Actions = {
  default: async (event) => {
    await api(event, 'POST', '/api/v1/auth/logout');
    clearSessionCookie(event);
    redirect(303, '/login');
  }
};
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd frontend && npx vitest run --coverage=false`
Expected: all pass. Also run `npm run check` (svelte-check) — clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): auth guard hooks, layout, login with 2FA step, logout"
```

---

### Task 15: Registration page

**Files:**
- Create: `frontend/src/routes/register/[token]/+page.server.ts`, `frontend/src/routes/register/[token]/+page.svelte`, `frontend/src/routes/register/[token]/page.server.test.ts`

**Interfaces:**
- Consumes: `registerSchema`, `parseForm`, `api` (mock pattern from Task 14).
- Produces: `load` → `{email}` on valid invite, or `{invalid: message}` on 404/410; `default` action → `{success: true, username}` on 201, `fail` otherwise.

- [ ] **Step 1: Write the failing test**

`frontend/src/routes/register/[token]/page.server.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/server/api', async (orig) => {
  const mod = (await orig()) as object;
  return { ...mod, api: vi.fn() };
});
vi.mock('$env/dynamic/private', () => ({ env: {} }));

import { api } from '$lib/server/api';
import { actions, load } from './+page.server';

function formEvent(fields: Record<string, string>) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.set(k, v);
  return {
    request: new Request('http://t.est', { method: 'POST', body: fd }),
    params: { token: 'tok123' },
    cookies: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
    url: new URL('http://t.est/register/tok123'),
    fetch: vi.fn(),
    locals: { user: null }
  } as never;
}

beforeEach(() => vi.clearAllMocks());

describe('load', () => {
  it('returns invite email when valid', async () => {
    vi.mocked(api).mockResolvedValue({ status: 200, data: { email: 'a@b.c' } });
    const res = await load(formEvent({}));
    expect(res).toEqual({ email: 'a@b.c' });
    expect(api).toHaveBeenCalledWith(expect.anything(), 'GET', '/api/v1/register/tok123');
  });

  it('maps 404/410 to invalid states', async () => {
    vi.mocked(api).mockResolvedValue({ status: 404, data: { detail: 'Invite not found' } });
    expect(await load(formEvent({}))).toEqual({ invalid: 'Invite not found' });
    vi.mocked(api).mockResolvedValue({ status: 410, data: { detail: 'Invite expired' } });
    expect(await load(formEvent({}))).toEqual({ invalid: 'Invite expired' });
  });
});

describe('register action', () => {
  const good = { username: 'Newbie1', password: 'hunter2!!', confirm: 'hunter2!!' };

  it('registers and reports success', async () => {
    vi.mocked(api).mockResolvedValue({ status: 201, data: { username: 'NEWBIE1' } });
    const res = await actions.default(formEvent(good));
    expect(res).toEqual({ success: true, username: 'NEWBIE1' });
    expect(api).toHaveBeenCalledWith(expect.anything(), 'POST', '/api/v1/register/tok123',
      { username: 'Newbie1', password: 'hunter2!!' });
  });

  it('rejects invalid form input locally', async () => {
    const res = await actions.default(formEvent({ ...good, confirm: 'different1' }));
    expect(res).toMatchObject({ status: 400 });
    expect(api).not.toHaveBeenCalled();
  });

  it('surfaces backend errors (409 taken, 410 gone, 503 down)', async () => {
    vi.mocked(api).mockResolvedValue({ status: 409, data: { detail: 'Username already taken' } });
    let res = await actions.default(formEvent(good));
    expect(res).toMatchObject({ status: 409, data: { message: 'Username already taken' } });
    vi.mocked(api).mockResolvedValue({ status: 503, data: { detail: 'Game server temporarily unavailable' } });
    res = await actions.default(formEvent(good));
    expect(res).toMatchObject({ status: 503 });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run --coverage=false`
Expected: FAIL — module not found

- [ ] **Step 3: Write the implementation**

`frontend/src/routes/register/[token]/+page.server.ts`:

```ts
import { fail } from '@sveltejs/kit';
import { registerSchema } from '$lib/schemas';
import { api } from '$lib/server/api';
import { parseForm } from '$lib/server/forms';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const { status, data } = await api<{ email?: string; detail?: string }>(
    event, 'GET', `/api/v1/register/${event.params.token}`);
  if (status !== 200) return { invalid: data.detail ?? 'This invite link is not valid' };
  return { email: data.email };
};

export const actions: Actions = {
  default: async (event) => {
    const parsed = await parseForm(event.request, registerSchema);
    if (!parsed.ok) return fail(400, parsed);
    const { status, data } = await api<{ username?: string; detail?: string }>(
      event, 'POST', `/api/v1/register/${event.params.token}`,
      { username: parsed.data.username, password: parsed.data.password });
    if (status === 201) return { success: true, username: data.username };
    return fail(status, {
      message: data.detail ?? 'Registration failed',
      values: { username: parsed.data.username }
    });
  }
};
```

`frontend/src/routes/register/[token]/+page.svelte`:

```svelte
<script lang="ts">
  import { enhance } from '$app/forms';
  import FieldErrors from '$lib/components/FieldErrors.svelte';
  let { data, form } = $props();
</script>

<div class="mx-auto max-w-sm rounded border border-stone-300 bg-white p-6 shadow-sm">
  {#if data.invalid}
    <h1 class="mb-2 text-lg font-semibold">Invite not valid</h1>
    <p class="text-sm text-stone-600">{data.invalid}</p>
  {:else if form?.success}
    <h1 class="mb-2 text-lg font-semibold">Account created</h1>
    <p class="text-sm text-stone-600">
      Your account <b>{form.username}</b> is ready. Use it in the game client, or
      <a href="/login" class="underline">log in to the portal</a> to manage it.
    </p>
  {:else}
    <h1 class="mb-1 text-lg font-semibold">Create your account</h1>
    <p class="mb-4 text-sm text-stone-500">Invited: {data.email}</p>
    <form method="POST" use:enhance>
      <label class="mb-1 block text-sm" for="username">Username</label>
      <input id="username" name="username" value={form?.values?.username ?? ''}
        class="w-full rounded border border-stone-300 px-3 py-2" />
      <FieldErrors errors={form?.errors?.username} />
      <label class="mb-1 mt-3 block text-sm" for="password">Password</label>
      <input id="password" name="password" type="password"
        class="w-full rounded border border-stone-300 px-3 py-2" />
      <FieldErrors errors={form?.errors?.password} />
      <label class="mb-1 mt-3 block text-sm" for="confirm">Confirm password</label>
      <input id="confirm" name="confirm" type="password"
        class="w-full rounded border border-stone-300 px-3 py-2" />
      <FieldErrors errors={form?.errors?.confirm} />
      {#if form?.message}<p class="mt-2 text-sm text-red-600">{form.message}</p>{/if}
      <button class="mt-4 w-full rounded bg-stone-900 py-2 text-stone-100">Create account</button>
    </form>
    <p class="mt-3 text-xs text-stone-500">
      Username: 3–20 letters or numbers. Password: 8–16 characters (game client limit).
    </p>
  {/if}
</div>
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd frontend && npx vitest run --coverage=false` — all pass; `npm run check` clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/register
git commit -m "feat(frontend): invite registration page"
```

---

### Task 16: Account page (password + 2FA)

**Files:**
- Create: `frontend/src/routes/account/+page.server.ts`, `frontend/src/routes/account/+page.svelte`, `frontend/src/routes/account/page.server.test.ts`

**Interfaces:**
- Consumes: `passwordChangeSchema`, `codeSchema`, `disable2faSchema`, `parseForm`, `api`; `locals.user` from hooks (guard guarantees non-null here).
- Produces action names: `password`, `setup2fa`, `confirm2fa`, `disable2fa`. `setup2fa` returns `{setup: {secret, otpauth_uri, qr_svg}}`; `confirm2fa` returns `{enabled: true}`; `password` returns `{passwordChanged: true}`; `disable2fa` returns `{disabled: true}`.

- [ ] **Step 1: Write the failing test**

`frontend/src/routes/account/page.server.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/server/api', async (orig) => {
  const mod = (await orig()) as object;
  return { ...mod, api: vi.fn() };
});
vi.mock('$env/dynamic/private', () => ({ env: {} }));

import { api } from '$lib/server/api';
import { actions } from './+page.server';

function formEvent(fields: Record<string, string>) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.set(k, v);
  return {
    request: new Request('http://t.est', { method: 'POST', body: fd }),
    cookies: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
    url: new URL('http://t.est/account'),
    fetch: vi.fn(),
    locals: { user: { username: 'BOB', email: null, totp_enabled: false, is_admin: false } }
  } as never;
}

beforeEach(() => vi.clearAllMocks());

describe('password action', () => {
  const good = { current_password: 'oldpass99', new_password: 'newpass99', confirm: 'newpass99' };

  it('changes password', async () => {
    vi.mocked(api).mockResolvedValue({ status: 200, data: { ok: true } });
    const res = await actions.password(formEvent(good));
    expect(res).toEqual({ passwordChanged: true });
    expect(api).toHaveBeenCalledWith(expect.anything(), 'POST', '/api/v1/user/password',
      { current_password: 'oldpass99', new_password: 'newpass99' });
  });

  it('rejects mismatched confirm locally', async () => {
    const res = await actions.password(formEvent({ ...good, confirm: 'other9999' }));
    expect(res).toMatchObject({ status: 400 });
    expect(api).not.toHaveBeenCalled();
  });

  it('surfaces wrong current password', async () => {
    vi.mocked(api).mockResolvedValue({ status: 403, data: { detail: 'Current password is incorrect' } });
    const res = await actions.password(formEvent(good));
    expect(res).toMatchObject({ status: 403, data: { message: 'Current password is incorrect' } });
  });
});

describe('2fa actions', () => {
  it('setup2fa returns secret payload', async () => {
    const payload = { secret: 'ABCDEFGHIJKLMNOP', otpauth_uri: 'otpauth://x', qr_svg: '<svg/>' };
    vi.mocked(api).mockResolvedValue({ status: 200, data: payload });
    const res = await actions.setup2fa(formEvent({}));
    expect(res).toEqual({ setup: payload });
  });

  it('setup2fa surfaces 409', async () => {
    vi.mocked(api).mockResolvedValue({ status: 409, data: { detail: '2FA already enabled' } });
    const res = await actions.setup2fa(formEvent({}));
    expect(res).toMatchObject({ status: 409 });
  });

  it('confirm2fa validates code then confirms', async () => {
    let res = await actions.confirm2fa(formEvent({ code: 'abc' }));
    expect(res).toMatchObject({ status: 400 });
    vi.mocked(api).mockResolvedValue({ status: 200, data: { ok: true } });
    res = await actions.confirm2fa(formEvent({ code: '123456' }));
    expect(res).toEqual({ enabled: true });
    vi.mocked(api).mockResolvedValue({ status: 400, data: { detail: 'Invalid code' } });
    res = await actions.confirm2fa(formEvent({ code: '123456' }));
    expect(res).toMatchObject({ status: 400, data: { message: 'Invalid code', setupPending: true } });
  });

  it('disable2fa flows', async () => {
    vi.mocked(api).mockResolvedValue({ status: 200, data: { ok: true } });
    let res = await actions.disable2fa(formEvent({ password: 'pw', code: '123456' }));
    expect(res).toEqual({ disabled: true });
    vi.mocked(api).mockResolvedValue({ status: 403, data: { detail: 'Password is incorrect' } });
    res = await actions.disable2fa(formEvent({ password: 'pw', code: '123456' }));
    expect(res).toMatchObject({ status: 403 });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run --coverage=false`
Expected: FAIL — module not found

- [ ] **Step 3: Write the implementation**

`frontend/src/routes/account/+page.server.ts`:

```ts
import { fail } from '@sveltejs/kit';
import { codeSchema, disable2faSchema, passwordChangeSchema } from '$lib/schemas';
import { api } from '$lib/server/api';
import { parseForm } from '$lib/server/forms';
import type { Actions } from './$types';

type Detail = { detail?: string };

export const actions: Actions = {
  password: async (event) => {
    const parsed = await parseForm(event.request, passwordChangeSchema);
    if (!parsed.ok) return fail(400, parsed);
    const { status, data } = await api<Detail>(event, 'POST', '/api/v1/user/password', {
      current_password: parsed.data.current_password,
      new_password: parsed.data.new_password
    });
    if (status === 200) return { passwordChanged: true };
    return fail(status, { message: data.detail ?? 'Password change failed' });
  },

  setup2fa: async (event) => {
    const { status, data } = await api<
      { secret: string; otpauth_uri: string; qr_svg: string } & Detail
    >(event, 'POST', '/api/v1/user/2fa/setup');
    if (status === 200) {
      return { setup: { secret: data.secret, otpauth_uri: data.otpauth_uri, qr_svg: data.qr_svg } };
    }
    return fail(status, { message: data.detail ?? '2FA setup failed' });
  },

  confirm2fa: async (event) => {
    const parsed = await parseForm(event.request, codeSchema);
    if (!parsed.ok) return fail(400, { ...parsed, setupPending: true });
    const { status, data } = await api<Detail>(
      event, 'POST', '/api/v1/user/2fa/confirm', parsed.data);
    if (status === 200) return { enabled: true };
    return fail(status, { message: data.detail ?? 'Confirmation failed', setupPending: true });
  },

  disable2fa: async (event) => {
    const parsed = await parseForm(event.request, disable2faSchema);
    if (!parsed.ok) return fail(400, parsed);
    const { status, data } = await api<Detail>(
      event, 'POST', '/api/v1/user/2fa/disable', parsed.data);
    if (status === 200) return { disabled: true };
    return fail(status, { message: data.detail ?? 'Disable failed' });
  }
};
```

`frontend/src/routes/account/+page.svelte`:

```svelte
<script lang="ts">
  import { enhance } from '$app/forms';
  import FieldErrors from '$lib/components/FieldErrors.svelte';
  let { data, form } = $props();
  const user = $derived(data.user!);
  const totpOn = $derived((user.totp_enabled || form?.enabled) && !form?.disabled);
</script>

<h1 class="mb-6 text-xl font-semibold">Your account</h1>

<div class="grid gap-6 md:grid-cols-2">
  <section class="rounded border border-stone-300 bg-white p-5 shadow-sm">
    <h2 class="mb-3 font-medium">Profile</h2>
    <dl class="text-sm">
      <dt class="text-stone-500">Username</dt>
      <dd class="mb-2">{user.username}</dd>
      <dt class="text-stone-500">Email</dt>
      <dd>{user.email ?? '—'}</dd>
    </dl>
  </section>

  <section class="rounded border border-stone-300 bg-white p-5 shadow-sm">
    <h2 class="mb-3 font-medium">Change password</h2>
    {#if form?.passwordChanged}
      <p class="mb-2 text-sm text-green-700">Password changed. Other sessions were signed out.</p>
    {/if}
    <form method="POST" action="?/password" use:enhance>
      <label class="mb-1 block text-sm" for="current_password">Current password</label>
      <input id="current_password" name="current_password" type="password"
        class="w-full rounded border border-stone-300 px-3 py-2" />
      <FieldErrors errors={form?.errors?.current_password} />
      <label class="mb-1 mt-3 block text-sm" for="new_password">New password</label>
      <input id="new_password" name="new_password" type="password"
        class="w-full rounded border border-stone-300 px-3 py-2" />
      <FieldErrors errors={form?.errors?.new_password} />
      <label class="mb-1 mt-3 block text-sm" for="confirm">Confirm new password</label>
      <input id="confirm" name="confirm" type="password"
        class="w-full rounded border border-stone-300 px-3 py-2" />
      <FieldErrors errors={form?.errors?.confirm} />
      {#if form?.message && !form?.setupPending}
        <p class="mt-2 text-sm text-red-600">{form.message}</p>
      {/if}
      <button class="mt-4 rounded bg-stone-900 px-4 py-2 text-sm text-stone-100">Change password</button>
    </form>
  </section>

  <section class="rounded border border-stone-300 bg-white p-5 shadow-sm md:col-span-2">
    <h2 class="mb-3 font-medium">Two-factor authentication</h2>
    {#if form?.setup || form?.setupPending}
      {#if form?.setup}
        <div class="mb-3 flex items-start gap-4">
          <div class="shrink-0">{@html form.setup.qr_svg}</div>
          <div class="text-sm">
            <p class="mb-2">Scan with your authenticator app, or enter the code manually:</p>
            <code class="rounded bg-stone-100 px-2 py-1">{form.setup.secret}</code>
          </div>
        </div>
      {/if}
      <form method="POST" action="?/confirm2fa" use:enhance>
        <label class="mb-1 block text-sm" for="code">Enter the 6-digit code to confirm</label>
        <input id="code" name="code" inputmode="numeric" autocomplete="one-time-code"
          class="w-40 rounded border border-stone-300 px-3 py-2" />
        <FieldErrors errors={form?.errors?.code} />
        {#if form?.message && form?.setupPending}
          <p class="mt-2 text-sm text-red-600">{form.message}</p>
        {/if}
        <button class="mt-3 rounded bg-stone-900 px-4 py-2 text-sm text-stone-100">Enable 2FA</button>
      </form>
    {:else if totpOn}
      <p class="mb-3 text-sm text-green-700">2FA is enabled on your account.</p>
      <form method="POST" action="?/disable2fa" use:enhance class="flex flex-wrap items-end gap-3">
        <div>
          <label class="mb-1 block text-sm" for="d_password">Password</label>
          <input id="d_password" name="password" type="password"
            class="rounded border border-stone-300 px-3 py-2" />
        </div>
        <div>
          <label class="mb-1 block text-sm" for="d_code">Current code</label>
          <input id="d_code" name="code" inputmode="numeric"
            class="w-32 rounded border border-stone-300 px-3 py-2" />
        </div>
        <button class="rounded border border-red-700 px-4 py-2 text-sm text-red-700">Disable 2FA</button>
      </form>
      {#if form?.message}<p class="mt-2 text-sm text-red-600">{form.message}</p>{/if}
    {:else}
      {#if form?.disabled}<p class="mb-2 text-sm text-stone-600">2FA has been disabled.</p>{/if}
      <p class="mb-3 text-sm text-stone-600">Protect your account with an authenticator app.</p>
      <form method="POST" action="?/setup2fa" use:enhance>
        <button class="rounded bg-stone-900 px-4 py-2 text-sm text-stone-100">Set up 2FA</button>
      </form>
      {#if form?.message}<p class="mt-2 text-sm text-red-600">{form.message}</p>{/if}
    {/if}
  </section>
</div>
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd frontend && npx vitest run --coverage=false` — all pass; `npm run check` clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/account
git commit -m "feat(frontend): account page with password change and 2FA management"
```

---

### Task 17: Admin pages + frontend coverage gate

**Files:**
- Create: `frontend/src/routes/admin/+layout.svelte`, and per section: `frontend/src/routes/admin/invites/{+page.server.ts,+page.svelte,page.server.test.ts}`, `frontend/src/routes/admin/accounts/{...same trio}`, `frontend/src/routes/admin/admins/{...}`, `frontend/src/routes/admin/audit/{+page.server.ts,+page.svelte}` (audit has load only — its test lives in `page.server.test.ts` too)

**Interfaces:**
- Consumes: `inviteSchema`, `grantAdminSchema`, `parseForm`, `api`; hooks guard already restricts `/admin/*` to admins.
- Produces:
  - invites: `load` → `{invites}`; actions `send` (email), `revoke` (hidden `id`).
  - accounts: `load` reads `?search=&page=` → `{accounts, total, page, pages, search}`; actions `lock`/`unlock` (hidden `username`).
  - admins: `load` → `{admins}`; actions `grant` (username), `revoke` (hidden `account_id`).
  - audit: `load` reads `?action=&page=` → `{entries, total, page, pages, action}`.

- [ ] **Step 1: Write the failing tests**

All four tests share the mock pattern from Task 14 (`vi.mock('$lib/server/api')` + `formEvent`). `frontend/src/routes/admin/invites/page.server.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/server/api', async (orig) => {
  const mod = (await orig()) as object;
  return { ...mod, api: vi.fn() };
});
vi.mock('$env/dynamic/private', () => ({ env: {} }));

import { api } from '$lib/server/api';
import { actions, load } from './+page.server';

function formEvent(fields: Record<string, string>, search = '') {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.set(k, v);
  return {
    request: new Request('http://t.est', { method: 'POST', body: fd }),
    cookies: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
    url: new URL(`http://t.est/admin/invites${search}`),
    fetch: vi.fn(),
    locals: { user: { username: 'BOSS', email: null, totp_enabled: false, is_admin: true } }
  } as never;
}

beforeEach(() => vi.clearAllMocks());

it('load lists pending invites', async () => {
  vi.mocked(api).mockResolvedValue({ status: 200, data: { items: [{ id: 1, email: 'a@b.c' }] } });
  expect(await load(formEvent({}))).toEqual({ invites: [{ id: 1, email: 'a@b.c' }] });
});

it('send action validates email then posts', async () => {
  let res = await actions.send(formEvent({ email: 'bad' }));
  expect(res).toMatchObject({ status: 400 });
  expect(api).not.toHaveBeenCalled();

  vi.mocked(api).mockResolvedValue({ status: 201, data: { id: 2, email: 'a@b.c' } });
  res = await actions.send(formEvent({ email: 'a@b.c' }));
  expect(res).toEqual({ sent: 'a@b.c' });

  vi.mocked(api).mockResolvedValue({ status: 502, data: { detail: 'Failed to send invite email' } });
  res = await actions.send(formEvent({ email: 'a@b.c' }));
  expect(res).toMatchObject({ status: 502, data: { message: 'Failed to send invite email' } });
});

it('revoke action deletes by id', async () => {
  vi.mocked(api).mockResolvedValue({ status: 200, data: { ok: true } });
  const res = await actions.revoke(formEvent({ id: '3' }));
  expect(res).toEqual({ revoked: true });
  expect(api).toHaveBeenCalledWith(expect.anything(), 'DELETE', '/api/v1/admin/invites/3');
  vi.mocked(api).mockResolvedValue({ status: 404, data: { detail: 'Invite not found' } });
  expect(await actions.revoke(formEvent({ id: '9' }))).toMatchObject({ status: 404 });
});
```

`frontend/src/routes/admin/accounts/page.server.test.ts` (same harness; URL `/admin/accounts`):

```ts
it('load forwards search and page params', async () => {
  vi.mocked(api).mockResolvedValue({ status: 200,
    data: { items: [{ username: 'A' }], total: 1, page: 2, pages: 3 } });
  const res = await load(formEvent({}, '?search=alp&page=2'));
  expect(api).toHaveBeenCalledWith(expect.anything(), 'GET',
    '/api/v1/admin/accounts?search=alp&page=2');
  expect(res).toEqual({ accounts: [{ username: 'A' }], total: 1, page: 2, pages: 3, search: 'alp' });
});

it('lock and unlock post to the right endpoints', async () => {
  vi.mocked(api).mockResolvedValue({ status: 200, data: { ok: true } });
  expect(await actions.lock(formEvent({ username: 'VICTIM' }))).toEqual({ done: true });
  expect(api).toHaveBeenCalledWith(expect.anything(), 'POST',
    '/api/v1/admin/accounts/VICTIM/lock');
  expect(await actions.unlock(formEvent({ username: 'VICTIM' }))).toEqual({ done: true });
  vi.mocked(api).mockResolvedValue({ status: 400, data: { detail: 'Cannot lock your own account' } });
  expect(await actions.lock(formEvent({ username: 'BOSS' }))).toMatchObject({ status: 400 });
});
```

`frontend/src/routes/admin/admins/page.server.test.ts` (same harness):

```ts
it('load lists admins', async () => {
  vi.mocked(api).mockResolvedValue({ status: 200, data: { items: [{ account_id: 1 }] } });
  expect(await load(formEvent({}))).toEqual({ admins: [{ account_id: 1 }] });
});

it('grant validates then posts; revoke deletes; last-admin error surfaces', async () => {
  let res = await actions.grant(formEvent({ username: '!' }));
  expect(res).toMatchObject({ status: 400 });
  vi.mocked(api).mockResolvedValue({ status: 201, data: { username: 'NEW' } });
  expect(await actions.grant(formEvent({ username: 'NewMin' }))).toEqual({ granted: 'NEW' });
  vi.mocked(api).mockResolvedValue({ status: 200, data: { ok: true } });
  expect(await actions.revoke(formEvent({ account_id: '5' }))).toEqual({ revoked: true });
  expect(api).toHaveBeenCalledWith(expect.anything(), 'DELETE', '/api/v1/admin/admins/5');
  vi.mocked(api).mockResolvedValue({ status: 400, data: { detail: 'Cannot remove the last admin' } });
  expect(await actions.revoke(formEvent({ account_id: '1' })))
    .toMatchObject({ status: 400, data: { message: 'Cannot remove the last admin' } });
});
```

`frontend/src/routes/admin/audit/page.server.test.ts` (same harness, load only):

```ts
it('load forwards filter and page', async () => {
  vi.mocked(api).mockResolvedValue({ status: 200,
    data: { items: [{ action: 'login.success' }], total: 1, page: 1, pages: 1 } });
  const res = await load(formEvent({}, '?action=login.success&page=1'));
  expect(api).toHaveBeenCalledWith(expect.anything(), 'GET',
    '/api/v1/admin/audit?action=login.success&page=1');
  expect(res).toEqual({ entries: [{ action: 'login.success' }], total: 1, page: 1, pages: 1,
    action: 'login.success' });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run --coverage=false`
Expected: FAIL — modules not found

- [ ] **Step 3: Write the implementations**

`frontend/src/routes/admin/+layout.svelte`:

```svelte
<script lang="ts">
  import { page } from '$app/state';
  let { children } = $props();
  const tabs = [
    ['/admin/invites', 'Invites'],
    ['/admin/accounts', 'Accounts'],
    ['/admin/admins', 'Admins'],
    ['/admin/audit', 'Audit log']
  ] as const;
</script>

<nav class="mb-6 flex gap-1 border-b border-stone-300 text-sm">
  {#each tabs as [href, label]}
    <a {href}
      class="rounded-t px-4 py-2 {page.url.pathname.startsWith(href)
        ? 'bg-white font-medium'
        : 'text-stone-500 hover:text-stone-800'}">{label}</a>
  {/each}
</nav>
{@render children()}
```

`frontend/src/routes/admin/invites/+page.server.ts`:

```ts
import { fail } from '@sveltejs/kit';
import { inviteSchema } from '$lib/schemas';
import { api } from '$lib/server/api';
import { parseForm } from '$lib/server/forms';
import type { Actions, PageServerLoad } from './$types';

type Detail = { detail?: string };

export const load: PageServerLoad = async (event) => {
  const { data } = await api<{ items: unknown[] }>(event, 'GET', '/api/v1/admin/invites');
  return { invites: data.items ?? [] };
};

export const actions: Actions = {
  send: async (event) => {
    const parsed = await parseForm(event.request, inviteSchema);
    if (!parsed.ok) return fail(400, parsed);
    const { status, data } = await api<Detail>(
      event, 'POST', '/api/v1/admin/invites', parsed.data);
    if (status === 201) return { sent: parsed.data.email };
    return fail(status, { message: data.detail ?? 'Invite failed', values: parsed.data });
  },
  revoke: async (event) => {
    const fd = await event.request.formData();
    const { status, data } = await api<Detail>(
      event, 'DELETE', `/api/v1/admin/invites/${fd.get('id')}`);
    if (status === 200) return { revoked: true };
    return fail(status, { message: data.detail ?? 'Revoke failed' });
  }
};
```

`frontend/src/routes/admin/invites/+page.svelte`:

```svelte
<script lang="ts">
  import { enhance } from '$app/forms';
  import FieldErrors from '$lib/components/FieldErrors.svelte';
  let { data, form } = $props();
</script>

<section class="mb-6 rounded border border-stone-300 bg-white p-5 shadow-sm">
  <h2 class="mb-3 font-medium">Send an invite</h2>
  {#if form?.sent}<p class="mb-2 text-sm text-green-700">Invite sent to {form.sent}.</p>{/if}
  <form method="POST" action="?/send" use:enhance class="flex items-end gap-3">
    <div>
      <label class="mb-1 block text-sm" for="email">Email address</label>
      <input id="email" name="email" value={form?.values?.email ?? ''}
        class="w-72 rounded border border-stone-300 px-3 py-2" />
      <FieldErrors errors={form?.errors?.email} />
    </div>
    <button class="rounded bg-stone-900 px-4 py-2 text-sm text-stone-100">Send invite</button>
  </form>
  {#if form?.message}<p class="mt-2 text-sm text-red-600">{form.message}</p>{/if}
</section>

<section class="rounded border border-stone-300 bg-white shadow-sm">
  <h2 class="border-b border-stone-200 px-5 py-3 font-medium">Pending invites</h2>
  <div class="overflow-x-auto">
    <table class="w-full text-left text-sm">
      <thead><tr class="text-stone-500">
        <th class="px-5 py-2">Email</th><th class="px-5 py-2">Sent</th>
        <th class="px-5 py-2">Expires</th><th class="px-5 py-2"></th>
      </tr></thead>
      <tbody>
        {#each data.invites as inv (inv.id)}
          <tr class="border-t border-stone-100">
            <td class="px-5 py-2">{inv.email}</td>
            <td class="px-5 py-2">{new Date(inv.created_at).toLocaleDateString()}</td>
            <td class="px-5 py-2">{new Date(inv.expires_at).toLocaleDateString()}</td>
            <td class="px-5 py-2 text-right">
              <form method="POST" action="?/revoke" use:enhance>
                <input type="hidden" name="id" value={inv.id} />
                <button class="text-red-700 hover:underline">Revoke</button>
              </form>
            </td>
          </tr>
        {:else}
          <tr><td class="px-5 py-3 text-stone-500" colspan="4">No pending invites.</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</section>
```

`frontend/src/routes/admin/accounts/+page.server.ts`:

```ts
import { fail, type RequestEvent } from '@sveltejs/kit';
import { api } from '$lib/server/api';
import type { Actions, PageServerLoad } from './$types';

type Detail = { detail?: string };

export const load: PageServerLoad = async (event) => {
  const search = event.url.searchParams.get('search') ?? '';
  const page = event.url.searchParams.get('page') ?? '1';
  const qs = new URLSearchParams({ search, page }).toString();
  const { data } = await api<{ items: unknown[]; total: number; page: number; pages: number }>(
    event, 'GET', `/api/v1/admin/accounts?${qs}`);
  return { accounts: data.items ?? [], total: data.total ?? 0,
           page: data.page ?? 1, pages: data.pages ?? 1, search };
};

async function act(event: RequestEvent, verb: 'lock' | 'unlock') {
  const fd = await event.request.formData();
  const { status, data } = await api<Detail>(
    event, 'POST', `/api/v1/admin/accounts/${fd.get('username')}/${verb}`);
  if (status === 200) return { done: true };
  return fail(status, { message: data.detail ?? `${verb} failed` });
}

export const actions: Actions = {
  lock: (event) => act(event, 'lock'),
  unlock: (event) => act(event, 'unlock')
};
```

`frontend/src/routes/admin/accounts/+page.svelte`:

```svelte
<script lang="ts">
  import { enhance } from '$app/forms';
  let { data, form } = $props();
</script>

<form method="GET" class="mb-4 flex gap-3">
  <input name="search" value={data.search} placeholder="Search username…"
    class="w-64 rounded border border-stone-300 px-3 py-2 text-sm" />
  <button class="rounded bg-stone-900 px-4 py-2 text-sm text-stone-100">Search</button>
</form>
{#if form?.message}<p class="mb-3 text-sm text-red-600">{form.message}</p>{/if}

<div class="overflow-x-auto rounded border border-stone-300 bg-white shadow-sm">
  <table class="w-full text-left text-sm">
    <thead><tr class="text-stone-500">
      <th class="px-4 py-2">Username</th><th class="px-4 py-2">Email</th>
      <th class="px-4 py-2">Joined</th><th class="px-4 py-2">Last login</th>
      <th class="px-4 py-2">2FA</th><th class="px-4 py-2">Status</th><th class="px-4 py-2"></th>
    </tr></thead>
    <tbody>
      {#each data.accounts as a (a.id)}
        <tr class="border-t border-stone-100">
          <td class="px-4 py-2 font-medium">{a.username}{#if a.is_admin}<span class="ml-1 rounded bg-stone-200 px-1 text-xs">admin</span>{/if}</td>
          <td class="px-4 py-2">{a.email ?? a.invited_email ?? '—'}</td>
          <td class="px-4 py-2">{a.joindate ? new Date(a.joindate).toLocaleDateString() : '—'}</td>
          <td class="px-4 py-2">{a.last_login ? new Date(a.last_login).toLocaleDateString() : '—'}</td>
          <td class="px-4 py-2">{a.totp_enabled ? 'on' : 'off'}</td>
          <td class="px-4 py-2">{a.locked ? '🔒 locked' : 'active'}</td>
          <td class="px-4 py-2 text-right">
            <form method="POST" action={a.locked ? '?/unlock' : '?/lock'} use:enhance>
              <input type="hidden" name="username" value={a.username} />
              <button class="hover:underline {a.locked ? 'text-stone-700' : 'text-red-700'}">
                {a.locked ? 'Unlock' : 'Lock'}
              </button>
            </form>
          </td>
        </tr>
      {:else}
        <tr><td class="px-4 py-3 text-stone-500" colspan="7">No accounts found.</td></tr>
      {/each}
    </tbody>
  </table>
</div>

{#if data.pages > 1}
  <div class="mt-4 flex gap-2 text-sm">
    {#each Array.from({ length: data.pages }, (_, i) => i + 1) as p}
      <a href="?search={data.search}&page={p}"
        class="rounded px-3 py-1 {p === data.page ? 'bg-stone-900 text-stone-100' : 'bg-white'}">{p}</a>
    {/each}
  </div>
{/if}
```

`frontend/src/routes/admin/admins/+page.server.ts`:

```ts
import { fail } from '@sveltejs/kit';
import { grantAdminSchema } from '$lib/schemas';
import { api } from '$lib/server/api';
import { parseForm } from '$lib/server/forms';
import type { Actions, PageServerLoad } from './$types';

type Detail = { detail?: string; username?: string };

export const load: PageServerLoad = async (event) => {
  const { data } = await api<{ items: unknown[] }>(event, 'GET', '/api/v1/admin/admins');
  return { admins: data.items ?? [] };
};

export const actions: Actions = {
  grant: async (event) => {
    const parsed = await parseForm(event.request, grantAdminSchema);
    if (!parsed.ok) return fail(400, parsed);
    const { status, data } = await api<Detail>(
      event, 'POST', '/api/v1/admin/admins', parsed.data);
    if (status === 201) return { granted: data.username };
    return fail(status, { message: data.detail ?? 'Grant failed', values: parsed.data });
  },
  revoke: async (event) => {
    const fd = await event.request.formData();
    const { status, data } = await api<Detail>(
      event, 'DELETE', `/api/v1/admin/admins/${fd.get('account_id')}`);
    if (status === 200) return { revoked: true };
    return fail(status, { message: data.detail ?? 'Revoke failed' });
  }
};
```

`frontend/src/routes/admin/admins/+page.svelte`:

```svelte
<script lang="ts">
  import { enhance } from '$app/forms';
  import FieldErrors from '$lib/components/FieldErrors.svelte';
  let { data, form } = $props();
</script>

<section class="mb-6 rounded border border-stone-300 bg-white p-5 shadow-sm">
  <h2 class="mb-3 font-medium">Grant portal admin</h2>
  {#if form?.granted}<p class="mb-2 text-sm text-green-700">{form.granted} is now an admin.</p>{/if}
  <form method="POST" action="?/grant" use:enhance class="flex items-end gap-3">
    <div>
      <label class="mb-1 block text-sm" for="username">Game account username</label>
      <input id="username" name="username" value={form?.values?.username ?? ''}
        class="w-64 rounded border border-stone-300 px-3 py-2" />
      <FieldErrors errors={form?.errors?.username} />
    </div>
    <button class="rounded bg-stone-900 px-4 py-2 text-sm text-stone-100">Grant</button>
  </form>
  {#if form?.message}<p class="mt-2 text-sm text-red-600">{form.message}</p>{/if}
</section>

<section class="rounded border border-stone-300 bg-white shadow-sm">
  <h2 class="border-b border-stone-200 px-5 py-3 font-medium">Portal admins</h2>
  <table class="w-full text-left text-sm">
    <tbody>
      {#each data.admins as a (a.account_id)}
        <tr class="border-t border-stone-100">
          <td class="px-5 py-2 font-medium">{a.username}</td>
          <td class="px-5 py-2 text-stone-500">
            since {new Date(a.granted_at).toLocaleDateString()}
            {a.granted_by === null ? '(env seed)' : ''}
          </td>
          <td class="px-5 py-2 text-right">
            <form method="POST" action="?/revoke" use:enhance>
              <input type="hidden" name="account_id" value={a.account_id} />
              <button class="text-red-700 hover:underline">Revoke</button>
            </form>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</section>
```

`frontend/src/routes/admin/audit/+page.server.ts`:

```ts
import { api } from '$lib/server/api';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const action = event.url.searchParams.get('action') ?? '';
  const page = event.url.searchParams.get('page') ?? '1';
  const qs = new URLSearchParams({ action, page }).toString();
  const { data } = await api<{ items: unknown[]; total: number; page: number; pages: number }>(
    event, 'GET', `/api/v1/admin/audit?${qs}`);
  return { entries: data.items ?? [], total: data.total ?? 0,
           page: data.page ?? 1, pages: data.pages ?? 1, action };
};
```

`frontend/src/routes/admin/audit/+page.svelte`:

```svelte
<script lang="ts">
  let { data } = $props();
  const ACTIONS = ['', 'invite.sent', 'invite.redeemed', 'invite.revoked', 'account.created',
    'password.changed', '2fa.enabled', '2fa.disabled', 'account.locked', 'account.unlocked',
    'admin.granted', 'admin.revoked', 'login.success', 'login.failed'];
</script>

<form method="GET" class="mb-4 flex gap-3 text-sm">
  <select name="action" class="rounded border border-stone-300 px-3 py-2">
    {#each ACTIONS as a}
      <option value={a} selected={a === data.action}>{a || 'All actions'}</option>
    {/each}
  </select>
  <button class="rounded bg-stone-900 px-4 py-2 text-stone-100">Filter</button>
</form>

<div class="overflow-x-auto rounded border border-stone-300 bg-white shadow-sm">
  <table class="w-full text-left text-sm">
    <thead><tr class="text-stone-500">
      <th class="px-4 py-2">When</th><th class="px-4 py-2">Action</th>
      <th class="px-4 py-2">Target</th><th class="px-4 py-2">Actor</th>
      <th class="px-4 py-2">Detail</th>
    </tr></thead>
    <tbody>
      {#each data.entries as e}
        <tr class="border-t border-stone-100">
          <td class="px-4 py-2 whitespace-nowrap">{new Date(e.at).toLocaleString()}</td>
          <td class="px-4 py-2"><code class="text-xs">{e.action}</code></td>
          <td class="px-4 py-2">{e.target}</td>
          <td class="px-4 py-2">{e.actor_account_id ?? '—'}</td>
          <td class="px-4 py-2 text-xs text-stone-500">{e.detail ? JSON.stringify(e.detail) : ''}</td>
        </tr>
      {:else}
        <tr><td class="px-4 py-3 text-stone-500" colspan="5">No entries.</td></tr>
      {/each}
    </tbody>
  </table>
</div>

{#if data.pages > 1}
  <div class="mt-4 flex gap-2 text-sm">
    {#each Array.from({ length: data.pages }, (_, i) => i + 1) as p}
      <a href="?action={data.action}&page={p}"
        class="rounded px-3 py-1 {p === data.page ? 'bg-stone-900 text-stone-100' : 'bg-white'}">{p}</a>
    {/each}
  </div>
{/if}
```

- [ ] **Step 4: Run tests, then enforce the frontend coverage gate**

Run: `cd frontend && npx vitest run --coverage=false` — all pass.
Run: `cd frontend && npx vitest run --coverage` — **must pass the 100% thresholds** over `src/lib/**/*.ts`, `src/**/*.server.ts`, `src/hooks.server.ts`. Add tests for any uncovered branch (common stragglers: `??` fallbacks in loads, `values` redaction, cookie `secure` branch).
Run: `npm run check && npm run lint` — clean.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): admin invites, accounts, admins, audit pages; 100% coverage gate"
```

---

### Task 18: Dockerfiles, compose, env template, README

**Files:**
- Create: `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/.dockerignore`, `backend/.dockerignore`, `docker-compose.yml`, `.env.template`, `README.md`, `.gitignore` (repo root)

**Interfaces:**
- Consumes: the finished backend (uvicorn factory `app.main:create_app`, alembic) and frontend (`node build`).
- Produces: `docker compose up -d --build` brings up the portal against a running RealmMaster stack.

- [ ] **Step 1: Write the deployment files**

`backend/Dockerfile`:

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync alembic upgrade head && uv run --no-sync uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8000"]
```

`backend/.dockerignore`:

```
__pycache__
*.db
.coverage
tests
.env
```

`frontend/Dockerfile`:

```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/package.json /app/package-lock.json ./
RUN npm ci --omit=dev
COPY --from=build /app/build ./build
EXPOSE 3000
CMD ["node", "build"]
```

`frontend/.dockerignore`:

```
node_modules
build
.svelte-kit
e2e
```

`docker-compose.yml`:

```yaml
services:
  backend:
    build: ./backend
    restart: unless-stopped
    environment:
      PORTAL_DATABASE_URL: "sqlite+aiosqlite:////data/portal.db"
      PORTAL_ACORE_AUTH_URL: "${PORTAL_ACORE_AUTH_URL}"
      PORTAL_SOAP_URL: "${PORTAL_SOAP_URL:-http://ac-worldserver:7878/}"
      PORTAL_SOAP_USER: "${PORTAL_SOAP_USER}"
      PORTAL_SOAP_PASS: "${PORTAL_SOAP_PASS}"
      PORTAL_SMTP_HOST: "${PORTAL_SMTP_HOST}"
      PORTAL_SMTP_PORT: "${PORTAL_SMTP_PORT:-587}"
      PORTAL_SMTP_USER: "${PORTAL_SMTP_USER:-}"
      PORTAL_SMTP_PASS: "${PORTAL_SMTP_PASS:-}"
      PORTAL_SMTP_FROM: "${PORTAL_SMTP_FROM}"
      PORTAL_SMTP_STARTTLS: "${PORTAL_SMTP_STARTTLS:-true}"
      PORTAL_INTERNAL_API_KEY: "${PORTAL_INTERNAL_API_KEY}"
      PORTAL_PUBLIC_BASE_URL: "${PORTAL_PUBLIC_BASE_URL}"
      PORTAL_INVITE_TTL_DAYS: "${PORTAL_INVITE_TTL_DAYS:-7}"
      PORTAL_SESSION_TTL_DAYS: "${PORTAL_SESSION_TTL_DAYS:-7}"
      PORTAL_TOTP_ISSUER: "${PORTAL_TOTP_ISSUER:-AzerothCore}"
      PORTAL_ADMIN_USERNAMES: "${PORTAL_ADMIN_USERNAMES:-}"
    volumes:
      - appdata:/data
    networks:
      - portal
      - realmmaster

  frontend:
    build: ./frontend
    restart: unless-stopped
    environment:
      ORIGIN: "${PORTAL_PUBLIC_BASE_URL}"
      BACKEND_URL: "http://backend:8000"
      INTERNAL_API_KEY: "${PORTAL_INTERNAL_API_KEY}"
      PORT: "3000"
    ports:
      - "${PORTAL_HTTP_PORT:-8080}:3000"
    depends_on:
      - backend
    networks:
      - portal

volumes:
  appdata:

networks:
  portal: {}
  realmmaster:
    external: true
    name: "${REALMMASTER_NETWORK}"
```

`.env.template` (copy to `.env` and fill in):

```bash
# ── RealmMaster wiring ────────────────────────────────────────────────
# Docker network of the running RealmMaster stack (`docker network ls`)
REALMMASTER_NETWORK=azerothcore-realmmaster_default

# Read-only MySQL user for acore_auth (create it once, see README)
PORTAL_ACORE_AUTH_URL=mysql+asyncmy://portal_ro:CHANGE_ME@ac-mysql:3306/acore_auth

# Dedicated GM account for the portal's SOAP calls (see README)
PORTAL_SOAP_URL=http://ac-worldserver:7878/
PORTAL_SOAP_USER=CHANGE_ME
PORTAL_SOAP_PASS=CHANGE_ME

# ── Email (any SMTP relay you control) ────────────────────────────────
PORTAL_SMTP_HOST=CHANGE_ME
PORTAL_SMTP_PORT=587
PORTAL_SMTP_USER=
PORTAL_SMTP_PASS=
PORTAL_SMTP_FROM=noreply@example.com
PORTAL_SMTP_STARTTLS=true

# ── Portal itself ─────────────────────────────────────────────────────
# Public URL players use (also the CSRF ORIGIN for the frontend)
PORTAL_PUBLIC_BASE_URL=https://portal.example.com
# Host port the frontend listens on
PORTAL_HTTP_PORT=8080
# Shared secret between frontend and backend: `openssl rand -hex 32`
PORTAL_INTERNAL_API_KEY=CHANGE_ME
# Comma-separated game accounts seeded as portal admins on startup
PORTAL_ADMIN_USERNAMES=
# Shown in authenticator apps and invite emails
PORTAL_TOTP_ISSUER=AzerothCore
PORTAL_INVITE_TTL_DAYS=7
PORTAL_SESSION_TTL_DAYS=7
```

Root `.gitignore`:

```
.env
node_modules/
```

`README.md` must cover, in this order (write real prose, not placeholders):

1. What the portal is (one paragraph) + screenshot placeholder omitted.
2. **Prerequisites**: a running RealmMaster stack; SOAP enabled (`SOAP_PORT=7878` in the stack's env, `AC_SOAP_PORT` wired — already the RealmMaster default); an SMTP relay.
3. **One-time AzerothCore setup**, with exact commands:
   - Dedicated SOAP GM account, from the worldserver console: `account create portalsoap <strong-password>` then `account set gmlevel portalsoap 3 -1`.
   - Read-only MySQL user, from the stack's mysql container:
     `docker exec -it ac-mysql mysql -uroot -p -e "CREATE USER 'portal_ro'@'%' IDENTIFIED BY 'CHANGE_ME'; GRANT SELECT ON acore_auth.* TO 'portal_ro'@'%';"`
   - Verify the SOAP commands this AC build supports (`account set email`, `account set 2fa ... off`) via the console `help account set`; note the Task 6 fallback if absent.
4. **Install**: `cp .env.template .env`, fill it, `docker compose up -d --build`, then check `docker compose logs backend` for the health line and hit `http://<host>:8080`.
5. **First admin**: set `PORTAL_ADMIN_USERNAMES=<your game account>` before first start (seeded at startup); log in and manage further admins in the UI.
6. **Backups**: the SQLite volume — `docker run --rm -v <project>_appdata:/data -v $(pwd):/backup alpine cp /data/portal.db /backup/portal-$(date +%F).db` — plus a note that game accounts live in the stack's own MySQL backups.
7. **Development**: backend `cd backend && uv run fastapi dev app/main.py` (needs a dev stack or env pointing at one), `uv run pytest`; frontend `cd frontend && npm run dev`, `npx vitest run --coverage`; e2e per Task 19.
8. **Security model** (three sentences: SOAP-only writes, SELECT-only MySQL, internal API key + sessions).

- [ ] **Step 2: Build and boot against the dev RealmMaster stack**

```bash
docker compose build
docker compose up -d
docker compose logs backend --tail 20
curl -fsS http://localhost:8080/  # expect 303 → /login HTML flow via browser
```

Expected: both containers healthy; backend log shows alembic migration + uvicorn start; visiting `http://localhost:8080` redirects to the login page. **This step needs the RealmMaster stack running with `REALMMASTER_NETWORK` set correctly** — verify SOAP + MySQL connectivity via `curl -fsS -H "X-Internal-Key: $PORTAL_INTERNAL_API_KEY" http://<backend-container-ip>:8000/api/v1/health` or `docker compose exec frontend wget -qO- http://backend:8000/api/v1/health` and confirm `"acore_auth": "ok", "soap": "ok"`.
Also verify the Task 6 NOTE now: from the worldserver console run `help account set` — confirm `2fa` accepts `off` and whether `email` exists; adjust `SoapClient.set_email`/`disable_2fa` + their tests if not.

- [ ] **Step 3: Commit**

```bash
git add backend/Dockerfile backend/.dockerignore frontend/Dockerfile frontend/.dockerignore docker-compose.yml .env.template README.md .gitignore
git commit -m "feat: docker compose deployment joining the RealmMaster network"
```

---

### Task 19: Playwright e2e smoke (manual / CI-optional)

**Files:**
- Create: `frontend/playwright.config.ts`, `frontend/e2e/portal.spec.ts`

**Interfaces:**
- Consumes: the running compose stack from Task 18 (`PORTAL_E2E_BASE_URL`, default `http://localhost:8080`) plus direct backend access for test setup (`PORTAL_E2E_BACKEND_URL` reachable from the host — for e2e runs, temporarily publish the backend port with a compose override, or run `docker compose exec`; simplest: `docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d` where the override adds `ports: ["18000:8000"]` to backend).
- Produces: one smoke spec: admin sends invite (via API) → register → login → change password → login with new password. Excluded from coverage; not run in the default test script.

- [ ] **Step 1: Install and configure**

```bash
cd frontend && npm install -D @playwright/test && npx playwright install chromium
```

Create `docker-compose.e2e.yml` (repo root):

```yaml
services:
  backend:
    ports:
      - "18000:8000"
```

`frontend/playwright.config.ts`:

```ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'e2e',
  use: { baseURL: process.env.PORTAL_E2E_BASE_URL ?? 'http://localhost:8080' },
  retries: 0
});
```

- [ ] **Step 2: Write the spec**

`frontend/e2e/portal.spec.ts`:

```ts
import { expect, test } from '@playwright/test';

const BACKEND = process.env.PORTAL_E2E_BACKEND_URL ?? 'http://localhost:18000';
const KEY = process.env.PORTAL_INTERNAL_API_KEY ?? '';
const ADMIN_USER = process.env.PORTAL_E2E_ADMIN_USER ?? '';
const ADMIN_PASS = process.env.PORTAL_E2E_ADMIN_PASS ?? '';

async function backendApi(method: string, path: string, body?: unknown, token?: string) {
  const res = await fetch(`${BACKEND}${path}`, {
    method,
    headers: {
      'X-Internal-Key': KEY,
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: body ? JSON.stringify(body) : undefined
  });
  return { status: res.status, data: await res.json() };
}

test('invite → register → login → change password', async ({ page }) => {
  test.skip(!KEY || !ADMIN_USER, 'set PORTAL_INTERNAL_API_KEY / PORTAL_E2E_ADMIN_USER(_PASS)');

  // Setup via API: log in as admin, send an invite, read the link out of the mailer?
  // No mailbox in e2e — instead create the invite row via the API and capture the link
  // from the admin UI is not possible either (token is only in the email).
  // So: use a dedicated test-only path — the invite email. For the smoke test we accept
  // SMTP pointing at MailHog (compose override) OR skip registration when unavailable:
  const login = await backendApi('POST', '/api/v1/auth/login',
    { username: ADMIN_USER, password: ADMIN_PASS });
  expect(login.status).toBe(200);

  // Portal login via UI with the admin account:
  await page.goto('/login');
  await page.getByLabel('Username').fill(ADMIN_USER);
  await page.getByLabel('Password').fill(ADMIN_PASS);
  await page.getByRole('button', { name: 'Log in' }).click();
  await expect(page).toHaveURL(/\/account$/);
  await expect(page.getByText(ADMIN_USER.toUpperCase())).toBeVisible();

  // Change password and back:
  await page.getByLabel('Current password').fill(ADMIN_PASS);
  await page.getByLabel('New password', { exact: true }).fill('e2eTmpPw1');
  await page.getByLabel('Confirm new password').fill('e2eTmpPw1');
  await page.getByRole('button', { name: 'Change password' }).click();
  await expect(page.getByText('Password changed')).toBeVisible();
  // restore
  await page.getByLabel('Current password').fill('e2eTmpPw1');
  await page.getByLabel('New password', { exact: true }).fill(ADMIN_PASS);
  await page.getByLabel('Confirm new password').fill(ADMIN_PASS);
  await page.getByRole('button', { name: 'Change password' }).click();
  await expect(page.getByText('Password changed')).toBeVisible();

  // Admin area loads:
  await page.goto('/admin/invites');
  await expect(page.getByText('Send an invite')).toBeVisible();
});
```

For full registration coverage add MailHog to `docker-compose.e2e.yml` (`mailhog/mailhog`, SMTP :1025, UI :8025, `PORTAL_SMTP_HOST=mailhog PORTAL_SMTP_PORT=1025 PORTAL_SMTP_STARTTLS=false`) and extend the spec: send invite in the admin UI, fetch the message from `http://localhost:8025/api/v2/messages`, extract the register link, complete the form, log in as the new user. Do this extension only if the smoke above is green and time allows — it's a documented follow-up, not a blocker.

- [ ] **Step 3: Run it (manual)**

```bash
docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build
cd frontend && PORTAL_INTERNAL_API_KEY=<key> PORTAL_E2E_ADMIN_USER=<admin> PORTAL_E2E_ADMIN_PASS=<pass> npx playwright test
```

Expected: 1 passed (or skipped with a clear message when env is absent).

- [ ] **Step 4: Commit**

```bash
git add frontend/playwright.config.ts frontend/e2e docker-compose.e2e.yml
git commit -m "test(e2e): portal smoke test against the compose stack"
```

---

## Final verification (after all tasks)

- [ ] `cd backend && uv run pytest` — all green, 100% coverage enforced.
- [ ] `cd backend && uv run ruff check .` — clean.
- [ ] `cd frontend && npx vitest run --coverage` — all green, 100% thresholds enforced.
- [ ] `cd frontend && npm run check && npm run lint && npm run build` — clean.
- [ ] `docker compose up -d --build` against the dev RealmMaster stack; `/api/v1/health` reports `acore_auth: ok, soap: ok`; manual walkthrough: invite → email received → register → game login works in client (or `account` row exists with correct verifier) → portal login → 2FA enable → game login prompts for token.
- [ ] Spec cross-check: every requirement in `docs/superpowers/specs/2026-08-29-account-portal-design.md` maps to a shipped feature; the two SOAP verifications from Task 6's NOTE are resolved and documented in the README.
