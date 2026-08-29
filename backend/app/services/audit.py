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
