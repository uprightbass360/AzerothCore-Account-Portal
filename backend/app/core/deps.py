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
