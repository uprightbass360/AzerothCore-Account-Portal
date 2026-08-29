# AzerothCore Account Portal

The AzerothCore Account Portal is a self-service web app that sits in front of an existing
AzerothCore/RealmMaster server. Players use it to register a game account from an
admin-issued invite link, change their password, and turn two-factor authentication on or
off — all without shell or database access. Guild officers and server admins get a small
admin area to issue invites, review accounts, promote other admins, and read an audit log
of who changed what. The portal never touches the game database directly: every account
mutation goes through the worldserver's SOAP command interface, and the only direct MySQL
access is a read-only user against `acore_auth` for looking up accounts. It ships as two
containers — a FastAPI backend and a SvelteKit frontend — that join your RealmMaster
stack's Docker network so they can reach `ac-worldserver` and `ac-mysql` by service name.

## Prerequisites

- A running RealmMaster stack (or any AzerothCore deployment using Docker Compose with
  `ac-worldserver` and `ac-mysql` containers on a shared Docker network).
- SOAP enabled on the worldserver: `SOAP_PORT=7878` in the stack's env, with `AC_SOAP_PORT`
  wired through to the worldserver config — this is already the RealmMaster default, so
  most deployments need no changes here.
- An SMTP relay the portal can send through (invite emails and password-reset-adjacent
  notices). Any relay you already control works — a real provider, an internal relay, or a
  local `postfix`/`msmtp` container.

## One-time AzerothCore setup

Do this once against your existing stack, before starting the portal.

**1. Create a dedicated SOAP GM account.** The portal authenticates its SOAP calls as a
game account with GM level 3, separate from any human GM account. From the worldserver
console:

```
account create portalsoap <strong-password>
account set gmlevel portalsoap 3 -1
```

Use this account's name and password as `PORTAL_SOAP_USER` / `PORTAL_SOAP_PASS` below.

**2. Create a read-only MySQL user for `acore_auth`.** The portal only ever `SELECT`s
account rows to look up usernames, emails, and lock state — it never writes to MySQL
directly. From the stack's `ac-mysql` container:

```bash
docker exec -it ac-mysql mysql -uroot -p -e "CREATE USER 'portal_ro'@'%' IDENTIFIED BY 'CHANGE_ME'; GRANT SELECT ON acore_auth.* TO 'portal_ro'@'%';"
```

Use the same password in `PORTAL_ACORE_AUTH_URL` below.

**3. Verify the SOAP commands your build supports.** Different AzerothCore builds carry
different console command sets. From the worldserver console, run:

```
help account set
```

Confirm `account set 2fa <username> off` is listed — the portal relies on it to disable
2FA server-side. Also check whether `account set email <username> <email> <email>` exists.
If your build does not have `account set email`, the portal's `SoapClient.set_email` call
will fault; the accepted fallback (see Task 6) is to make `set_email` a no-op that returns
`""` and keep the email address portal-side only, updating `SoapClient.set_email` and its
tests accordingly. Do this check before pointing the portal at a stack you care about.

## Install

```bash
cp .env.template .env
```

Fill in `.env`: `REALMMASTER_NETWORK` (find it with `docker network ls` — it's usually
`<project>_default` or `<project>_realmmaster`), `PORTAL_ACORE_AUTH_URL` with the
`portal_ro` password from step 2 above, `PORTAL_SOAP_USER`/`PORTAL_SOAP_PASS` from step 1,
your SMTP settings, `PORTAL_PUBLIC_BASE_URL` (the URL players will use — this also doubles
as the frontend's CSRF origin, so get it right), and `PORTAL_INTERNAL_API_KEY` (generate
one with `openssl rand -hex 32`).

Then build and start both containers:

```bash
docker compose up -d --build
```

Check the backend came up cleanly — you should see the alembic migration run followed by
the uvicorn startup line:

```bash
docker compose logs backend
```

Once that looks healthy, visit `http://<host>:8080` (or whatever `PORTAL_HTTP_PORT` you
set) in a browser. You should land on the login page.

## First admin

Before the first start, set `PORTAL_ADMIN_USERNAMES` in `.env` to your own game account
name (the one you'll register through an invite, or that already exists in `acore_auth`).
The backend seeds this list as portal admins on every startup, matching by account name.
Once you've registered and logged in as that account, you'll see the admin area and can
issue invites and promote further admins from the UI — you don't need to edit
`PORTAL_ADMIN_USERNAMES` again after that.

## Backups

The portal's own data (invites, admin flags, audit log) lives in a single SQLite file on
the `appdata` volume. Back it up with:

```bash
docker run --rm -v <project>_appdata:/data -v $(pwd):/backup alpine cp /data/portal.db /backup/portal-$(date +%F).db
```

Replace `<project>_appdata` with your actual volume name (`docker volume ls` if unsure —
by default it's `<compose-project-name>_appdata`). Game accounts themselves are not stored
by the portal at all; they live in the RealmMaster stack's own `acore_auth` database, so
back that up through your existing MySQL backup process, not through this one.

## Development

Backend:

```bash
cd backend
uv run fastapi dev app/main.py   # needs a dev stack, or PORTAL_* env vars pointing at one
uv run pytest
```

Frontend:

```bash
cd frontend
npm run dev
npx vitest run --coverage
```

End-to-end tests against a full stack are covered separately in Task 19.

## Security model

Every account mutation — creating an account, setting a password, toggling 2FA — is
performed exclusively through the worldserver's SOAP interface using a dedicated GM
account, so the portal never writes to the game database directly; its only direct MySQL
access is a `SELECT`-only user scoped to `acore_auth` for read lookups. The frontend and
backend containers communicate over an internal Docker network using a shared internal API
key (`PORTAL_INTERNAL_API_KEY`) that the browser never sees, while player-facing auth is
handled with server-side sessions issued after password (and optional TOTP) verification.

## Verifying the deployment

The checks below need a live RealmMaster stack and were **not** run as part of this
change (this environment has no RealmMaster stack to join) — run them after your first
real deployment.

**Health endpoint against the real stack.** With the portal joined to your RealmMaster
network and `.env` filled in with real credentials:

```bash
curl -fsS -H "X-Internal-Key: $PORTAL_INTERNAL_API_KEY" http://<backend-container-ip>:8000/api/v1/health
# or, from inside the frontend container:
docker compose exec frontend wget -qO- http://backend:8000/api/v1/health
```

Confirm the response is `{"status": "ok", "checks": {"acore_auth": "ok", "soap": "ok", ...}}`.
`acore_auth` failing means the `portal_ro` MySQL user or `PORTAL_ACORE_AUTH_URL` is wrong;
`soap` failing means the worldserver isn't reachable at `PORTAL_SOAP_URL` or the
`portalsoap` GM account/credentials are wrong.

**Worldserver console SOAP command support.** From the worldserver console, run
`help account set` and confirm:

- `account set 2fa <username> off` is accepted — this is required for the portal's
  "disable 2FA" flow to work.
- Whether `account set email <username> <email> <email>` exists. If it does not, apply the
  Task 6 fallback noted above: make `SoapClient.set_email` a no-op returning `""` and keep
  the email address portal-side only, and update its tests to match.

This local change verified everything that does not require a live RealmMaster stack:
both Docker images build cleanly, `docker compose config` resolves against a filled-in
`.env`, and a smoke boot with the `realmmaster` network pointed at a plain Docker
bridge network confirmed the backend runs its alembic migration and starts uvicorn, the
frontend serves the SvelteKit build and redirects `/` to `/login`, and the backend's health
endpoint responds with the expected shape (reporting `acore_auth`/`soap` as `"error"` and
overall `"degraded"`, since no real MySQL or worldserver was reachable — this is the
correct, expected result without a real stack, not a bug).
