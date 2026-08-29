import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_reader, get_soap
from app.core.security import hash_token
from app.db.base import utcnow
from app.db.models import Invite
from app.services.acore import AccountRow, AcoreReader
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
async def check_username(
    token: str,
    username: str,
    db: AsyncSession = Depends(get_db),
    reader: AcoreReader = Depends(get_reader),
) -> dict:
    await _valid_invite(token, db)
    if not USERNAME_RE.fullmatch(username):
        return {"valid": False, "available": False}
    return {"valid": True, "available": not await reader.username_exists(username)}


async def _maybe_repair(db: AsyncSession, inv: Invite, acct: AccountRow) -> dict | None:
    """A 409 on account creation can mean a prior redemption crashed after SOAP
    account_create succeeded but before the invite was marked used. If the existing
    account's email matches the invite's, treat this as that crashed redemption and
    repair the invite record instead of surfacing a plain conflict."""
    if acct.email is None or acct.email.lower() != inv.email.lower():
        return None
    inv.used_at = utcnow()
    inv.account_id = acct.id
    await record(db, "invite.redeemed", inv.email, detail={"repair": True})
    await db.commit()
    return {"username": acct.username}


@router.post("/{token}", status_code=201)
async def register(
    token: str,
    body: RegisterIn,
    db: AsyncSession = Depends(get_db),
    reader: AcoreReader = Depends(get_reader),
    soap: SoapClient = Depends(get_soap),
) -> dict:
    inv = await _valid_invite(token, db)
    if not USERNAME_RE.fullmatch(body.username):
        raise HTTPException(status_code=422, detail="Invalid username")
    if not PASSWORD_RE.fullmatch(body.password):
        raise HTTPException(status_code=422, detail="Invalid password")
    username = body.username.upper()
    existing = await reader.get_account(username)
    if existing is not None:
        repaired = await _maybe_repair(db, inv, existing)
        if repaired is not None:
            return repaired
        raise HTTPException(status_code=409, detail="Username already taken")

    try:
        await soap.account_create(username, body.password)
    except SoapError as exc:
        if "exist" in exc.message.lower():
            existing = await reader.get_account(username)
            if existing is not None:
                repaired = await _maybe_repair(db, inv, existing)
                if repaired is not None:
                    return repaired
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
