import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import admin, auth, email_change, health, register, user
from app.core.config import Settings, get_settings
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

    app = FastAPI(
        title="AzerothCore Account Portal",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    app.state.acore_engine = make_engine(settings.acore_auth_url)
    app.state.reader = AcoreReader(app.state.acore_engine)
    app.state.soap = SoapClient(settings.soap_url, settings.soap_user, settings.soap_pass)
    app.state.mailer = Mailer(settings)
    app.state.login_limiter = RateLimiter(rate=0.2, capacity=5)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(register.router)
    app.include_router(email_change.router)
    app.include_router(user.router)
    app.include_router(admin.router)

    @app.middleware("http")
    async def internal_key_guard(request: Request, call_next):
        # Enforced here (rather than per-router `dependencies=`) so it applies even to
        # paths that don't exist yet as routes in stub routers (Tasks 9-12 add them) --
        # FastAPI never runs router-level dependencies for a route that isn't registered.
        # Fail closed: every path requires the key except exactly "/api/v1/health"
        # (this also covers /docs, /redoc, /openapi.json and any unknown path).
        if request.url.path != "/api/v1/health":
            expected = request.app.state.settings.internal_api_key
            provided = request.headers.get("x-internal-key", "")
            # provided may contain arbitrary bytes smuggled in via latin-1 header
            # encoding; compare as bytes so garbage input yields 401, not a 500.
            if not hmac.compare_digest(provided.encode("latin-1", "replace"), expected.encode()):
                return JSONResponse(status_code=401, content={"detail": "Invalid internal API key"})
        return await call_next(request)

    @app.exception_handler(SoapError)
    async def soap_error_handler(request: Request, exc: SoapError) -> JSONResponse:
        logger.error("SOAP failure: %s", exc.message)
        return JSONResponse(
            status_code=503, content={"detail": "Game server temporarily unavailable"}
        )

    return app
