from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_reader, get_soap
from app.core.security import hash_token
from app.db.base import utcnow
from app.db.models import EmailChange
from app.services.acore import AcoreReader
from app.services.audit import record
from app.services.soap import SoapClient

router = APIRouter(prefix="/api/v1/email-change", tags=["email-change"])


async def _valid_change(token: str, db: AsyncSession) -> EmailChange:
    stmt = select(EmailChange).where(EmailChange.token_hash == hash_token(token))
    change = (await db.execute(stmt)).scalar_one_or_none()
    if change is None:
        raise HTTPException(status_code=404, detail="Confirmation link not found")
    if change.used_at is not None:
        raise HTTPException(status_code=410, detail="This confirmation link was already used")
    if change.expires_at < utcnow():
        raise HTTPException(status_code=410, detail="This confirmation link has expired")
    return change


@router.get("/{token}")
async def change_info(token: str, db: AsyncSession = Depends(get_db)) -> dict:
    change = await _valid_change(token, db)
    return {"new_email": change.new_email}


@router.post("/{token}")
async def confirm_change(
    token: str,
    db: AsyncSession = Depends(get_db),
    reader: AcoreReader = Depends(get_reader),
    soap: SoapClient = Depends(get_soap),
) -> dict:
    change = await _valid_change(token, db)
    acct = await reader.get_by_id(change.account_id)
    if acct is None:
        raise HTTPException(status_code=410, detail="Account no longer exists")
    await soap.set_email(acct.username, change.new_email)
    change.used_at = utcnow()
    await record(db, "email.changed", change.new_email, actor_account_id=change.account_id)
    await db.commit()
    return {"ok": True, "username": acct.username, "new_email": change.new_email}
