#!/usr/bin/env bash
# Local UX-test harness: seeded acore stub + fake SOAP + MailHog + backend + frontend dev.
# Usage: tools/uxtest/run.sh   (stop with tools/uxtest/stop.sh)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
UX="$ROOT/tools/uxtest"
DATA="$UX/.data"
PIDS="$UX/.pids"
mkdir -p "$DATA"
: > "$PIDS"

export PORTAL_DATABASE_URL="sqlite+aiosqlite:///$DATA/portal.db"
export PORTAL_ACORE_AUTH_URL="sqlite+aiosqlite:///$DATA/acore.db"
export PORTAL_SOAP_URL="http://127.0.0.1:7878/"
export PORTAL_SOAP_USER="uxtest"
export PORTAL_SOAP_PASS="uxtest"
export PORTAL_SMTP_HOST="127.0.0.1"
export PORTAL_SMTP_PORT="1025"
export PORTAL_SMTP_STARTTLS="false"
export PORTAL_SMTP_FROM="noreply@uxtest.local"
export PORTAL_INTERNAL_API_KEY="uxtest-key"
export PORTAL_PUBLIC_BASE_URL="http://localhost:5173"
export PORTAL_ADMIN_USERNAMES="TESTADMIN"
export PORTAL_SERVER_NAME="UXTest Realm"
export PORTAL_INVITE_TTL_DAYS="7"

echo "== seeding acore stub =="
rm -f "$DATA/portal.db"
(cd "$ROOT" && uv run --project backend python tools/uxtest/seed_acore.py)

echo "== migrating portal db =="
(cd "$ROOT/backend" && uv run alembic upgrade head)

echo "== mailhog =="
docker rm -f uxtest-mailhog >/dev/null 2>&1 || true
docker run -d --name uxtest-mailhog -p 1025:1025 -p 8025:8025 mailhog/mailhog >/dev/null

echo "== fake soap =="
(cd "$ROOT" && setsid nohup uv run --project backend python tools/uxtest/fake_soap.py \
  > "$DATA/fake_soap.log" 2>&1 & echo "soap $!" >> "$PIDS")

echo "== backend =="
(cd "$ROOT/backend" && setsid nohup uv run uvicorn --factory app.main:create_app \
  --host 127.0.0.1 --port 8000 > "$DATA/backend.log" 2>&1 & echo "backend $!" >> "$PIDS")

echo "== frontend (vite dev) =="
(cd "$ROOT/frontend" && BACKEND_URL="http://127.0.0.1:8000" INTERNAL_API_KEY="uxtest-key" \
  setsid nohup npm run dev -- --port 5173 --strictPort --host 0.0.0.0 > "$DATA/frontend.log" 2>&1 \
  & echo "frontend $!" >> "$PIDS")

sleep 4
echo
echo "Portal:   http://localhost:5173   (admin: TESTADMIN / uxtestpass1)"
echo "MailHog:  http://localhost:8025   (invite emails land here)"
echo "Backend:  http://127.0.0.1:8000/api/v1/health"
echo "Logs:     $DATA/*.log — stop with tools/uxtest/stop.sh"
