# AzerothCore Account Portal — Design

**Date:** 2026-08-29
**Status:** Approved design, pre-implementation
**Repo:** `azerothcore-account-portal` (separate from AzerothCore-RealmMaster)

## Purpose

An invite-only user registration and self-service account portal for an
AzerothCore server run on the RealmMaster stack, plus basic admin tooling.
Entirely self-hosted. Frontend is SvelteKit 2; backend is FastAPI. All account
writes go through AzerothCore's SOAP API over the RealmMaster docker network;
account reads come from the `acore_auth` database via a read-only MySQL user.

### Scope (v1)

- **Players:** register via emailed invite link, log in with game credentials,
  change password, enable/disable TOTP 2FA.
- **Admins:** send/revoke invites, list accounts, lock/unlock accounts,
  grant/revoke portal admins, view audit log.

### Out of scope (v1)

- Email-based password reset (admins use existing AC tools).
- GM levels, bans, character data, server status.
- Any writes to `acore_auth` via MySQL.

## Architecture

### Repo layout

```
azerothcore-account-portal/
├── docker-compose.yml        # frontend + backend, joins RealmMaster network (external)
├── .env.template             # all secrets/config, documented per-variable
├── frontend/                 # SvelteKit 2, adapter-node
│   └── src/routes/           # /register/[token], /login, /account, /admin
└── backend/                  # FastAPI + uv, SQLAlchemy, httpx
    ├── app/
    │   ├── api/              # routers: auth, register, user, admin
    │   ├── core/             # config, session auth, SRP6 verify, rate limiting
    │   ├── services/         # soap.py, mailer.py, acore_auth reader
    │   └── db/               # SQLite models + alembic migrations
    └── tests/
```

### Runtime topology

- **frontend** — the only service with a published port. All API calls happen
  server-side in SvelteKit (`+page.server.ts` form actions / load functions)
  against `http://backend:8000`; the browser never talks to FastAPI directly.
  The session cookie is set/read by the SvelteKit server, `HttpOnly; Secure;
  SameSite=Lax`.
- **backend** — no published ports. Joins the RealmMaster compose network
  (declared `external: true`; network name from env) and reaches:
  - `ac-worldserver:7878` — SOAP (`urn:AC` envelope), for all writes:
    `.account create`, `.account set password`, `.account set 2fa`,
    `.account lock`.
  - `ac-mysql` — read-only MySQL user (`GRANT SELECT ON acore_auth.*`,
    documented in README) for account listing, SRP6 salt/verifier lookup, and
    TOTP secret lookup.
- **appdata** named volume — the SQLite file. Backup = copy one file
  (documented in README; not covered by the stack's MySQL backups).
- The portal's own compose network (frontend↔backend) is separate and
  internal; only the backend also joins the stack network. The stack's compose
  file is never modified.

### Frontend↔backend trust

The session cookie value is forwarded as a bearer token on each server-side
request; FastAPI owns session validation. A shared `INTERNAL_API_KEY` header
ensures the backend only answers its own frontend even inside the docker
network.

## Data model (SQLite, Alembic migrations)

Everything else lives in `acore_auth` and is never duplicated.

### `invites`

`id`, `email`, `token_hash` (SHA-256 of the URL token — raw token appears only
in the email, never stored), `created_by` (admin account id), `created_at`,
`expires_at` (default 7 days, configurable), `used_at` (null until redeemed),
`account_id` (game account created from it, null until redeemed),
`revoked_at`.

One pending invite per email, enforced at the API layer (re-inviting revokes
and replaces).

### `sessions`

`id` (hash of a random 256-bit token — cookie holds the raw value),
`account_id`, `username` (denormalized for display), `created_at`,
`expires_at` (sliding, default 7 days), `ip`, `user_agent`, `revoked_at`.

Server-side sessions rather than JWT: instantly revocable when an admin locks
an account; no key management.

### `admins`

`account_id`, `username`, `granted_by`, `granted_at`.

Seeded at first startup from env `PORTAL_ADMIN_USERNAMES` (comma-separated,
resolved against `acore_auth.account` by name); afterwards existing admins
grant/revoke in the UI. Guard: the last admin cannot be revoked.

### `audit_log`

`id`, `at`, `actor_account_id` (null for system/registration events), `action`
(string enum: `invite.sent`, `invite.redeemed`, `invite.revoked`,
`account.created`, `password.changed`, `2fa.enabled`, `2fa.disabled`,
`account.locked`, `account.unlocked`, `admin.granted`, `admin.revoked`,
`login.success`, `login.failed`), `target` (username/email), `detail` (small
JSON, scrubbed of secrets).

Read-only view in the admin UI, newest first, filterable by action.

### Reads from `acore_auth` (SELECT only)

`account` (id, username, email, salt, verifier, totp_secret, locked,
last_login, joindate). No other tables, no triggers, no writes, ever. The
reader uses SQLAlchemy Core so tests can run it against a SQLite copy of the
schema.

## Auth & core flows

### Invite → registration

1. Admin enters an email → backend generates a 256-bit token, stores its hash,
   emails `https://<portal>/register/<token>` via SMTP (aiosmtplib;
   plain-text + simple HTML). SMTP failure = invite not created (atomic — no
   orphaned invites believed sent).
2. User opens the link → page validates the token (exists, unused, unexpired,
   unrevoked) → form: username + password (+ confirm). Username availability
   is checked live against `acore_auth.account`, enforcing AC constraints
   (≤20 chars, allowed charset, case-insensitive uniqueness).
3. Submit → SOAP `.account create <user> <pass>`, then `.account set email` to
   attach the invite's email (verify the exact command against this AC
   version during implementation; if absent, the email is surfaced from
   portal data only — never written via MySQL). Invite marked used, audit
   logged, user lands on the login page with a success message.

### Web login (SRP6)

- Backend reads `salt`, `verifier`, `totp_secret`, `locked` from
  `acore_auth.account`, computes the AzerothCore SRP6 verifier from the
  submitted username+password (g=7, standard N,
  `H(salt ‖ H(UPPER(user):UPPER(pass)))`, little-endian) and compares
  constant-time. No password ever goes to SOAP or MySQL for login.
- If `totp_secret` is set, a second step requires the 6-digit code (pyotp,
  ±1 window). Locked accounts receive a generic failure.
- Success → server-side session row + cookie. Failures audit-logged; per-IP
  and per-username rate limiting (in-process token bucket — single backend
  instance, no shared store).

### Password change (logged in)

Requires current password (SRP6 re-verify) → SOAP
`.account set password <user> <new> <new>` → all other sessions for the
account revoked.

### 2FA self-service (logged in)

Backend generates a base32 secret, shows QR (otpauth URI rendered as SVG
server-side) + manual code → user must submit a valid TOTP to confirm → only
then SOAP `.account set 2fa <user> <secret>`. Disable requires password +
current code. Issuer comes from env (default: realm name), mirroring the
RealmMaster scripts' convention.

## API surface

All consumed server-side by SvelteKit; prefix `/api/v1`.

```
POST   /auth/login                  → session (or 2fa_required challenge)
POST   /auth/login/2fa              → session
POST   /auth/logout
GET    /user                        → username, email, 2fa status, is_admin
POST   /user/password
POST   /user/2fa/setup              → secret + otpauth URI
POST   /user/2fa/confirm
POST   /user/2fa/disable
GET    /register/{token}            → invite validity + email
POST   /register/{token}            → create account
GET    /register/check-username
GET    /health                      → SOAP / MySQL / SMTP reachability

admin (guarded by admins table):
GET/POST     /admin/invites         (+ DELETE /admin/invites/{id})
GET          /admin/accounts        (?search=&page=)
POST         /admin/accounts/{username}/lock | /unlock
GET/POST     /admin/admins          (+ DELETE)
GET          /admin/audit
```

### Admin UI (`/admin`, visible only to portal admins)

- **Invites** — send, pending list with expiry, re-send (revoke + replace),
  revoke.
- **Accounts** — paginated list from `acore_auth.account` joined with portal
  data: username, email, joindate, last_login, 2FA on/off, locked, invited-by
  (when portal-created). Actions: lock / unlock.
- **Admins** — grant/revoke by username (must exist in `acore_auth`);
  last-admin guard.
- **Audit log** — filterable, newest first.

## Error handling

- SOAP and MySQL outages are the main failure modes. Every SOAP call: 5s
  timeout, one retry; on failure a clean "server temporarily unavailable"
  message and no half-applied action. Order of operations: external write
  first, then local DB commit (e.g. account created via SOAP before the invite
  is marked used; if the local commit then fails, the next redeem attempt hits
  the username-exists check, which is detected and repaired by marking the
  invite used).
- Registration/login never leak whether a username/email exists except where
  the flow requires it (the username availability check sits behind a valid
  invite token).
- Startup health check verifies SOAP reachability, MySQL read access, and SMTP
  connectivity (SMTP is a warning, not fatal); exposed at `/api/v1/health`
  for a future RealmMaster status-dashboard integration.

## Security notes

- Secrets in env only: SOAP credentials (a dedicated GM account for the
  portal — README documents creating it), read-only MySQL user, SMTP creds,
  `INTERNAL_API_KEY`, session secret. `.env.template` documents every
  variable.
- TOTP secrets and invite tokens are never logged; audit `detail` JSON is
  scrubbed.
- CSRF: SvelteKit form actions' origin checking + SameSite cookie.

## Testing

**Coverage target: 100%, enforced in CI and locally.**

- **Backend:** pytest with `--cov --cov-fail-under=100`. Unit tests for SRP6
  verification (known salt/verifier vectors generated with AC's algorithm),
  TOTP, invite lifecycle, session/admin guards, rate limiting. Integration
  tests with a fake SOAP server (small XML responder, httpx-mockable) and a
  seeded SQLite plus a stubbed `acore_auth` (SQLite copy of the `account`
  schema — the reader is dialect-portable by design).
- **Frontend:** Vitest with coverage thresholds at 100 for form validation and
  server-side logic. Playwright smoke test (register → login → change
  password) against the docker-compose dev stack; run manually or as an
  optional CI job — excluded from the coverage gate.
- TDD throughout.

## Dependencies (verified 2026-08-29)

All libraries below were verified against PyPI/npm for current version and
2025–2026 maintenance activity, and their intended-usage APIs checked against
official docs. Nothing selected is deprecated or abandoned.

### Backend (Python 3.12+, managed with uv)

| Library | Version (pin) | Role / intended usage |
|---|---|---|
| fastapi[standard] | 0.141.x | App framework; `[standard]` bundles uvicorn, TestClient deps, fastapi-cli |
| SQLAlchemy | 2.0.x | Async end-to-end: `create_async_engine`, `AsyncSession`; Core for the `acore_auth` reader (dialect-portable) |
| alembic | 1.19.x | Migrations, async template (`alembic init -t async`, `connection.run_sync`) |
| aiosqlite | 0.22.x | Async SQLite dialect (`sqlite+aiosqlite://`) for app DB |
| asyncmy | 0.2.x | Async MySQL dialect (`mysql+asyncmy://`) for read-only `acore_auth`; handles MySQL 8 `caching_sha2_password`; more active than aiomysql |
| httpx | >=0.28,<1.0 | SOAP POSTs: `AsyncClient(auth=(user, pass))`, `content=` XML bytes. **Yellow flag:** stable 0.28.1 is from Dec 2024 and 1.0 is in dev pre-releases — pin below 1.0, expect API changes at 1.0 |
| aiosmtplib | 5.1.x | Invite mail: `EmailMessage` + `aiosmtplib.send(..., start_tls=True)` |
| pyotp | 2.10.x | `random_base32()`, `TOTP.provisioning_uri(name=..., issuer_name=...)`, `totp.verify(code, valid_window=1)` |
| segno | 1.6.x | QR as SVG string via `segno.make(uri).svg_inline()` — pure Python, zero deps (chosen over `qrcode`, which needs Pillow/pypng and only writes SVG to streams) |
| pydantic-settings | 2.15.x | `BaseSettings` + `SettingsConfigDict(env_prefix="PORTAL_")`, cached instance injected via `Depends` |
| pytest / pytest-cov / pytest-asyncio | 9.x / 7.x / 1.4.x | `asyncio_mode = "auto"`; pytest-asyncio only (not anyio's plugin — never both); `--cov --cov-fail-under=100` |
| respx | 0.23.x | httpx mocking for SOAP/unit tests |
| ruff | latest | Lint + format |

Because httpx and aiosmtplib make the stack async anyway, all DB access is
async (no sync-in-threadpool mixing); sync SQLAlchemy calls inside `async def`
are forbidden.

### Frontend (SvelteKit 2, scaffolded with `npx sv create` — `create-svelte` is deprecated)

| Library | Version | Role / intended usage |
|---|---|---|
| svelte | 5.x | Runes mode (`$state`, `$derived`, `$props`) |
| @sveltejs/kit | 2.70+ | `+page.server.ts` `load`/`actions`, `fail()`/`redirect()`, `event.fetch` to backend, `event.cookies`, auth guard in `hooks.server.ts` `handle`, `use:enhance` |
| @sveltejs/adapter-node | 5.5.x | Docker deploy: `node build`; **must set `ORIGIN`** env (or `PROTOCOL_HEADER`/`HOST_HEADER` behind a proxy) or form actions fail CSRF origin checks; backend URL via `$env/dynamic/private` (runtime, not build-time); `.env` not auto-loaded in prod — env comes from compose |
| zod | 4.x | Form validation in actions: `schema.safeParse` + `z.flattenError()`; v4 APIs (`z.email()` top-level, `error:` callback). **No superforms** — plain form actions + a small shared parse/fail helper; FastAPI re-validates everything, and superforms' machinery isn't earned by ~8 simple forms |
| tailwindcss + @tailwindcss/vite | 4.x | CSS-first config: Vite plugin + `@import "tailwindcss"` in `app.css`; no `tailwind.config.js`; theme tokens via `@theme` |
| vitest | 4.x | Node-env unit tests for validation/action helpers (100% threshold) |
| @testing-library/svelte | 5.4.x | Component tests only where components hold real logic (still the scaffold/official-docs default; `vitest-browser-svelte` noted as the emerging alternative if needs grow) |
| @playwright/test | 1.62.x | E2E smoke (register → login → password change), `sv` add-on scaffold; excluded from coverage gate |
| eslint 10 (flat config) + eslint-plugin-svelte 3.x, prettier + prettier-plugin-svelte | scaffold versions | As shipped by `sv create` add-ons |

## Development & deployment

- Local dev runs against a dev RealmMaster stack; the portal deploys on the
  prod box alongside the stack without modifying the stack's compose file.
- Backend tooling: uv, ruff, pytest. Frontend: `npx sv create` scaffold with
  eslint, prettier, vitest, playwright, tailwindcss add-ons.
