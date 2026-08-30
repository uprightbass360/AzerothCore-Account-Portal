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
    # The SvelteKit server forwards the real visitor's address; trusting the
    # header is safe because the internal-key middleware means only our own
    # frontend can reach this API at all.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _checked_account(
    body: LoginIn, request: Request, db: AsyncSession, reader: AcoreReader
) -> AccountRow:
    ip = _client_ip(request)
    limiter = request.app.state.login_limiter
    if not (limiter.allow(f"ip:{ip}") and limiter.allow(f"user:{body.username.upper()}")):
        raise HTTPException(status_code=429, detail="Too many attempts, try again later")
    acct = await reader.get_account(body.username)
    ok = (
        acct is not None
        and not await reader.is_banned(acct.id)
        and verify_password(body.username, body.password, acct.salt, acct.verifier)
    )
    if not ok:
        await record(db, "login.failed", body.username.upper(), detail={"ip": ip})
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return acct


async def _issue(request: Request, db: AsyncSession, acct: AccountRow) -> dict:
    settings = request.app.state.settings
    raw, hashed = new_session_token()
    sess = PortalSession(
        id=hashed,
        account_id=acct.id,
        username=acct.username,
        expires_at=utcnow() + timedelta(days=settings.session_ttl_days),
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.add(sess)
    await record(
        db, "login.success", acct.username, actor_account_id=acct.id, detail={"ip": sess.ip}
    )
    await db.commit()
    return {"token": raw, "expires_at": sess.expires_at.isoformat() + "Z"}


@router.post("/login")
async def login(
    body: LoginIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    reader: AcoreReader = Depends(get_reader),
) -> dict:
    acct = await _checked_account(body, request, db, reader)
    if acct.totp_secret:
        return {"status": "2fa_required"}
    return await _issue(request, db, acct)


@router.post("/login/2fa")
async def login_2fa(
    body: TwoFaIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    reader: AcoreReader = Depends(get_reader),
) -> dict:
    acct = await _checked_account(body, request, db, reader)
    if not acct.totp_secret or not totp.verify_code(
        totp.secret_from_db(acct.totp_secret), body.code
    ):
        await record(db, "login.failed", acct.username, detail={"reason": "2fa"})
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid code")
    return await _issue(request, db, acct)


@router.post("/logout")
async def logout(
    sess: PortalSession = Depends(current_session), db: AsyncSession = Depends(get_db)
) -> dict:
    sess.revoked_at = utcnow()
    await db.commit()
    return {"ok": True}
