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

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)])

PAGE_SIZE = 25
AUDIT_PAGE_SIZE = 50


class InviteIn(BaseModel):
    email: EmailStr


class AdminIn(BaseModel):
    username: str


@router.post("/invites", status_code=201)
async def create_invite(
    body: InviteIn,
    request: Request,
    sess: PortalSession = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    mailer: Mailer = Depends(get_mailer),
) -> dict:
    settings = request.app.state.settings
    raw, hashed = new_session_token()
    link = f"{settings.public_base_url}/register/{raw}"
    try:
        await mailer.send_invite(body.email, link, settings.invite_ttl_days)
    except MailerError as exc:
        raise HTTPException(status_code=502, detail="Failed to send invite email") from exc

    replaced = await db.execute(
        update(Invite)
        .where(Invite.email == body.email, Invite.used_at.is_(None), Invite.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    if replaced.rowcount:
        await record(
            db,
            "invite.revoked",
            body.email,
            actor_account_id=sess.account_id,
            detail={"reason": "replaced"},
        )
    inv = Invite(
        email=body.email,
        token_hash=hashed,
        created_by=sess.account_id,
        expires_at=utcnow() + timedelta(days=settings.invite_ttl_days),
    )
    db.add(inv)
    await db.flush()
    await record(
        db,
        "invite.sent",
        body.email,
        actor_account_id=sess.account_id,
        detail={"invite_id": inv.id},
    )
    await db.commit()
    return {"id": inv.id, "email": inv.email, "expires_at": inv.expires_at.isoformat()}


@router.get("/invites")
async def list_invites(db: AsyncSession = Depends(get_db)) -> dict:
    stmt = (
        select(Invite)
        .where(Invite.used_at.is_(None), Invite.revoked_at.is_(None))
        .order_by(Invite.created_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": i.id,
                "email": i.email,
                "created_at": i.created_at.isoformat(),
                "expires_at": i.expires_at.isoformat(),
            }
            for i in rows
        ]
    }


@router.delete("/invites/{invite_id}")
async def revoke_invite(
    invite_id: int, sess: PortalSession = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    inv = await db.get(Invite, invite_id)
    if inv is None or inv.used_at is not None or inv.revoked_at is not None:
        raise HTTPException(status_code=404, detail="Invite not found")
    inv.revoked_at = utcnow()
    await record(db, "invite.revoked", inv.email, actor_account_id=sess.account_id)
    await db.commit()
    return {"ok": True}


@router.get("/accounts")
async def list_accounts(
    request: Request,
    search: str = "",
    page: int = 1,
    bots: bool = False,
    db: AsyncSession = Depends(get_db),
    reader: AcoreReader = Depends(get_reader),
) -> dict:
    exclude = None if bots else request.app.state.settings.bot_prefix_list
    rows, total = await reader.list_accounts(
        search=search, offset=(page - 1) * PAGE_SIZE, limit=PAGE_SIZE, exclude_prefixes=exclude
    )
    ids = [r.id for r in rows]
    banned = await reader.banned_ids(ids)
    admin_ids = set(
        (
            await db.execute(select(Admin.account_id).where(Admin.account_id.in_(ids or [0])))
        ).scalars()
    )
    invites = {
        i.account_id: i.email
        for i in (
            await db.execute(select(Invite).where(Invite.account_id.in_(ids or [0])))
        ).scalars()
    }
    items = [
        {
            "id": r.id,
            "username": r.username,
            "email": r.email,
            "joindate": r.joindate.isoformat() if r.joindate else None,
            "last_login": r.last_login.isoformat() if r.last_login else None,
            "totp_enabled": bool(r.totp_secret),
            "locked": r.id in banned,
            "is_admin": r.id in admin_ids,
            "invited_email": invites.get(r.id),
        }
        for r in rows
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": max(1, math.ceil(total / PAGE_SIZE)),
    }


@router.post("/accounts/{username}/lock")
async def lock_account(
    username: str,
    sess: PortalSession = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    reader: AcoreReader = Depends(get_reader),
    soap: SoapClient = Depends(get_soap),
) -> dict:
    acct = await reader.get_account(username)
    if acct is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if acct.id == sess.account_id:
        raise HTTPException(status_code=400, detail="Cannot lock your own account")
    await soap.ban(acct.username, "Locked via portal")
    await db.execute(
        update(PortalSession)
        .where(PortalSession.account_id == acct.id, PortalSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    await record(db, "account.locked", acct.username, actor_account_id=sess.account_id)
    await db.commit()
    return {"ok": True}


@router.post("/accounts/{username}/unlock")
async def unlock_account(
    username: str,
    sess: PortalSession = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    reader: AcoreReader = Depends(get_reader),
    soap: SoapClient = Depends(get_soap),
) -> dict:
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
    return {
        "items": [
            {
                "account_id": a.account_id,
                "username": a.username,
                "granted_by": a.granted_by,
                "granted_at": a.granted_at.isoformat(),
            }
            for a in rows
        ]
    }


@router.post("/admins", status_code=201)
async def grant_admin(
    body: AdminIn,
    sess: PortalSession = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    reader: AcoreReader = Depends(get_reader),
) -> dict:
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
async def revoke_admin(
    account_id: int,
    sess: PortalSession = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
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
async def list_audit(action: str = "", page: int = 1, db: AsyncSession = Depends(get_db)) -> dict:
    base = select(AuditLog)
    count = select(func.count()).select_from(AuditLog)
    if action:
        base, count = base.where(AuditLog.action == action), count.where(AuditLog.action == action)
    total = (await db.execute(count)).scalar_one()
    rows = (
        (
            await db.execute(
                base.order_by(AuditLog.at.desc(), AuditLog.id.desc())
                .offset((page - 1) * AUDIT_PAGE_SIZE)
                .limit(AUDIT_PAGE_SIZE)
            )
        )
        .scalars()
        .all()
    )
    items = [
        {
            "at": r.at.isoformat(),
            "actor_account_id": r.actor_account_id,
            "action": r.action,
            "target": r.target,
            "detail": r.detail,
        }
        for r in rows
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": max(1, math.ceil(total / AUDIT_PAGE_SIZE)),
    }
