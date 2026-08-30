from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.register import PASSWORD_RE
from app.core.deps import get_db, get_reader, get_soap
from app.core.security import hash_token
from app.db.base import utcnow
from app.db.models import PasswordReset, PortalSession
from app.services import totp
from app.services.acore import AcoreReader
from app.services.audit import record
from app.services.soap import SoapClient

router = APIRouter(prefix="/api/v1/password-reset", tags=["password-reset"])


class ResetIn(BaseModel):
    new_password: str
    code: str | None = None


async def _valid_reset(token: str, db: AsyncSession) -> PasswordReset:
    stmt = select(PasswordReset).where(PasswordReset.token_hash == hash_token(token))
    reset = (await db.execute(stmt)).scalar_one_or_none()
    if reset is None:
        raise HTTPException(status_code=404, detail="Reset link not found")
    if reset.used_at is not None:
        raise HTTPException(status_code=410, detail="This reset link was already used")
    if reset.expires_at < utcnow():
        raise HTTPException(status_code=410, detail="This reset link has expired")
    return reset


@router.get("/{token}")
async def reset_info(
    token: str,
    db: AsyncSession = Depends(get_db),
    reader: AcoreReader = Depends(get_reader),
) -> dict:
    reset = await _valid_reset(token, db)
    acct = await reader.get_by_id(reset.account_id)
    if acct is None:
        raise HTTPException(status_code=410, detail="Account no longer exists")
    return {"username": acct.username, "totp_required": bool(acct.totp_secret)}


@router.post("/{token}")
async def complete_reset(
    token: str,
    body: ResetIn,
    db: AsyncSession = Depends(get_db),
    reader: AcoreReader = Depends(get_reader),
    soap: SoapClient = Depends(get_soap),
) -> dict:
    reset = await _valid_reset(token, db)
    acct = await reader.get_by_id(reset.account_id)
    if acct is None:
        raise HTTPException(status_code=410, detail="Account no longer exists")
    if not PASSWORD_RE.fullmatch(body.new_password):
        raise HTTPException(status_code=422, detail="Invalid password")
    if acct.totp_secret:
        if not body.code:
            raise HTTPException(status_code=400, detail="2FA code required")
        if not totp.verify_code(totp.secret_from_db(acct.totp_secret), body.code):
            raise HTTPException(status_code=400, detail="Invalid code")
    await soap.set_password(acct.username, body.new_password)
    reset.used_at = utcnow()
    await db.execute(
        update(PortalSession)
        .where(PortalSession.account_id == acct.id, PortalSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    await record(db, "password.reset", acct.username, actor_account_id=acct.id)
    await db.commit()
    return {"ok": True, "username": acct.username}
