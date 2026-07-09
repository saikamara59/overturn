# Overturn Phase 2 — Multi-Tenancy Design

**Date:** 2026-07-09
**Status:** Approved (design discussion in session)

## Context and goal

Phase 1 (merged, deployed at https://overturn.up.railway.app) is a
single-tenant server: one env-configured admin, all runs in one pool. Phase 2
makes Overturn multi-tenant: **organizations** with **users**, **roles**, and
**hard data isolation**, so hand-picked customers can each work their own
denials without seeing anyone else's — and pay for their own LLM usage.

Decisions locked during design:
- **Org creation is owner-provisioned.** No public signup. The platform
  admin (you) creates orgs and mints their first invite. Self-serve is
  Phase 3+.
- **Per-org BYO Anthropic key.** Each org stores its own key (encrypted at
  rest); live runs bill the org. Orgs without a key operate dry-run only.
  The platform key is never used for tenant workloads.
- **Passwords + copy-paste invite links.** No email provider in Phase 2.
  Invites are single-use links shared out-of-band; "password reset" is an
  admin issuing a fresh invite to the same email.
- **Roles: Admin / Member.** Admin manages members, invites, and org
  settings (incl. API key), plus everything Member can do. Member uploads
  runs and works claims.
- **Minimal platform-admin screen** in the SPA for provisioning.
- **Isolation: app-level org scoping** (org_id + one scoping dependency;
  cross-org access → 404). Postgres RLS is deliberately deferred.

Thin-host rule unchanged: no appeal logic server-side; healthflow-agents
stays pinned at v0.3.0.

## Data model (Alembic migration 0002)

**orgs**
- `id` (uuid pk), `name` (unique), `status` (`active | disabled`)
- `anthropic_key_encrypted` (text, nullable) — Fernet ciphertext
- `anthropic_key_last4` (varchar(4), nullable) — display only
- `created_at`

**users**
- `id` (uuid pk), `email` (text; stored lowercased, unique index on
  `lower(email)` — no citext extension), `password_hash` (bcrypt)
- `is_platform_admin` (bool, default false)
- `created_at`

**memberships**
- `id` (uuid pk), `user_id` (fk), `org_id` (fk), `role` (`admin | member`)
- unique (`user_id`, `org_id`)

**invites**
- `id` (uuid pk), `token` (unique, 32-byte urlsafe random), `org_id` (fk)
- `role` (`admin | member`), `email` (nullable hint, shown on accept page)
- `created_by` (fk users), `created_at`, `expires_at` (created + 7 days)
- `used_at` (nullable), `used_by` (nullable fk users) — single-use

**runs** — add `org_id` (fk, NOT NULL, indexed). Claims and audit_events
inherit isolation through `run_id`.

**Migration data steps (0002):**
1. Create the four new tables.
2. Insert default org `Overturn HQ` (active).
3. Backfill every existing run's `org_id` to the default org, then set
   NOT NULL.
4. The demo run keeps its `is_demo` flag and remains publicly readable via
   the existing unauthenticated `/demo/*` endpoints regardless of its org.

**Startup seeding (replaces env-admin auth):** on web start, upsert a
platform-admin user from `ADMIN_EMAIL`/`ADMIN_PASSWORD` (create if missing;
update password hash if changed) with `is_platform_admin=True` and an admin
membership in the default org. Env vars keep their Phase 1 names so the
Railway deployment needs no variable changes beyond the new secret.

## Secrets and crypto

- Passwords: `bcrypt` (the `bcrypt` package directly, cost 12).
- Org API keys: Fernet symmetric encryption; new REQUIRED env
  `KEY_ENCRYPTION_SECRET` (urlsafe base64, 32 bytes — generated at deploy).
  Key is decrypted only in the worker at run time and in the API layer only
  to re-encrypt on rotation. Responses never contain the key; org settings
  show `last4` only.
- Invite tokens: `secrets.token_urlsafe(32)`, stored as given (they are
  single-use, short-lived, and revocable; hashing them adds lookup friction
  without a matching threat at this stage — revisit in the Phase 3 security
  pass).
- New dependency (server extra): `cryptography`, `bcrypt`.

## Authorization model

Session cookie now stores `user_id` and `org_id` (active org). Login
resolves the user's memberships; if the user has exactly one, it becomes the
active org; platform admins with no membership default to the default org.
Multi-org users get the first membership by join date (an org switcher is
out of scope; schema supports it).

FastAPI dependencies (in `server/api/deps.py`):
- `current_user` → User or 401.
- `current_org` → (User, Org, role) or 401/403; rejects `disabled` orgs
  with 403.
- `require_org_admin` → membership role == admin or 403.
- `require_platform_admin` → `is_platform_admin` or 403.
- `scoped_run(run_id)` / `scoped_claim(claim_id)` → the object **iff it
  belongs to the session's org**, else 404 (existence never leaks across
  orgs). All existing run/claim endpoints switch to these.

Permission matrix:

| Action | Member | Org Admin | Platform Admin |
|---|---|---|---|
| Upload runs, work/approve/export claims (own org) | ✅ | ✅ | ✅ (in own org context) |
| List members, change roles, remove members | — | ✅ | — |
| Create/revoke invites | — | ✅ | — |
| Set/rotate/clear org Anthropic key | — | ✅ | — |
| Create/list/disable orgs, mint first invite | — | — | ✅ |

## API changes (`/api/v1`)

Changed:
- `POST /auth/login` — now validates against `users` (bcrypt); response
  `{email, orgId, orgName, role, isPlatformAdmin}`. `GET /auth/me` same
  shape.
- `POST /runs` — requires membership; sets `run.org_id`; **live uploads 422
  unless the org has an API key configured** (message says so); dry-run
  always allowed.
- All `GET/POST/PATCH` run & claim endpoints — org-scoped via the
  dependencies above; foreign ids → 404.

New (org, `require_org_admin` unless noted):
- `GET /org` (any member) — `{id, name, role, hasApiKey, apiKeyLast4}`
- `PUT /org/api-key` `{key}` — validate shape (`sk-ant-` prefix), encrypt,
  store, return last4; `DELETE /org/api-key` clears it
- `GET /org/members`; `PATCH /org/members/{user_id}` `{role}`;
  `DELETE /org/members/{user_id}` (cannot remove the last admin — 409)
- `POST /org/invites` `{role, email?}` → `{inviteUrl, token, expiresAt}`;
  `GET /org/invites` (pending only); `DELETE /org/invites/{id}` (revoke)

New (invite acceptance, unauthenticated):
- `GET /invites/{token}` → `{orgName, role, email?, expiresAt}` or
  404/410 (unknown / used / expired)
- `POST /invites/{token}/accept` `{email, password}` — if the email is new,
  creates the user with that password; if the email already exists, the
  supplied password must match the EXISTING account's password (401
  otherwise) and the account gains the membership. Either way: membership
  created, invite burned, session logged in.

New (platform admin, `require_platform_admin`):
- `GET /admin/orgs` — orgs with member/run counts
- `POST /admin/orgs` `{name}` → org + first admin invite URL
- `PATCH /admin/orgs/{id}` `{status}` — disable/re-enable (disabled orgs:
  members 403 on login-scoped endpoints; worker skips their queued runs)

## Worker changes

- `claim_next_run` joins `orgs`, skips runs whose org is `disabled`.
- Agent construction per run: dry-run → `DryRunClient`; live → decrypt the
  org key and inject `anthropic.Anthropic(api_key=...)` as `client`. Live
  run whose org key was cleared between upload and processing → run fails
  with a clear error (no fallback to any platform key).

## SPA changes

- **Login** — unchanged UI; richer `me` payload drives role-gated nav.
- **Accept Invite** (`#/invite/<token>`, public) — shows org + role, asks
  email (prefilled from hint) + password, accepts, lands in Runs.
- **Org Settings** (`#/org`, org-admin only) — members table (role
  dropdown, remove), pending invites (create with role, copy link, revoke),
  API key card (status + last4, set/rotate/clear; explains live vs dry-run).
- **Platform Admin** (`#/admin`, platform-admin only) — orgs table
  (name, status, members, runs), create org → shows the first invite link
  to copy, disable/enable toggle.
- Runs/workbench screens unchanged apart from the org name in the top bar.
- The read-only public demo experience is unchanged.

## Config

New env (both services): `KEY_ENCRYPTION_SECRET` (required).
Existing `ADMIN_EMAIL`/`ADMIN_PASSWORD` now seed the platform-admin user.
`ANTHROPIC_API_KEY` becomes unused for tenant runs (may be removed from the
deployment; demo seeding is dry-run and never needed it).

## Error handling

- Cross-org object access: 404 (never 403 — no existence leak).
- Disabled org: 403 with a clear message on any org-scoped endpoint.
- Invites: 404 unknown token, 410 expired or already used, 409 revoking a
  used invite, 409 accepting when the email already belongs to a member of
  that org.
- Live upload without org key: 422 with remediation text.
- Removing/downgrading the last org admin: 409.

## Testing

- **pytest**: the permission matrix (every cell above), cross-org isolation
  (org A's session gets 404 on org B's run/claim/letter/zip — the critical
  suite), invite lifecycle (create → accept → reuse → 410; expiry; revoke),
  key encrypt/decrypt round-trip + last4, login against bcrypt users,
  platform-admin provisioning flow, worker org-key injection (fake client
  asserts the key reached the Anthropic client constructor), disabled-org
  behavior (API 403, worker skip), migration data steps (default org
  backfill).
- **Vitest**: Accept Invite, Org Settings, Platform Admin screens; role-
  gated nav rendering.
- **E2E (Playwright)**: platform admin logs in → creates org + invite →
  (new context) accepts invite → uploads dry-run batch → sees only own
  org's runs; original admin's org list unchanged.

## Out of scope (Phase 2)

Email sending, self-serve signup, org switcher UI, OAuth/SSO, Postgres RLS,
per-org quotas/billing, invite-token hashing, audit-log UI beyond the
existing workbench panel, org deletion (disable only).
