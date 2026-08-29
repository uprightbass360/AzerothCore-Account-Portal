from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/api/v1/health")
async def health(request: Request) -> dict:
    checks: dict[str, str] = {}
    try:
        await request.app.state.reader.ping()
        checks["acore_auth"] = "ok"
    except Exception:
        checks["acore_auth"] = "error"
    try:
        await request.app.state.soap.server_info()
        checks["soap"] = "ok"
    except Exception:
        checks["soap"] = "error"
    checks["smtp"] = "ok" if await request.app.state.mailer.ping() else "warn"
    degraded = checks["acore_auth"] == "error" or checks["soap"] == "error"
    return {"status": "degraded" if degraded else "ok", "checks": checks}
