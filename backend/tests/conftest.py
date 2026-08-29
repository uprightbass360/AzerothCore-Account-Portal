import pytest
from datetime import timedelta
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.security import new_session_token
from app.core.srp6 import calculate_verifier
from app.db.base import Base, make_engine, make_sessionmaker, utcnow
from app.db.models import Invite
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
