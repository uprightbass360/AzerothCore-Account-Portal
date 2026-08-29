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
