# Overturn Server — Phase 1 Design

**Date:** 2026-07-06
**Status:** Approved (design discussion in session)

## Context and goal

Overturn is becoming a product: a multi-tenant SaaS is the ambition, built in
phases. This spec covers **Phase 1 — the single-tenant server core**: a
deployed web application where an authenticated user uploads a remittance
file, the pipeline runs server-side in the background, and the Denial
Workbench becomes a served SPA whose approvals and letter edits **persist**.

Phasing (later phases get their own specs):
- **Phase 1 (this spec):** single-tenant server core.
- **Phase 2:** multi-tenancy — organizations, users, roles, per-org isolation.
- **Phase 3:** product hardening — claim workflow states beyond Submitted,
  outcome tracking, notifications, billing, HIPAA/BAA posture.

The server is a **thin host** per the repo doctrine: all appeal logic,
redaction, contracts, and safety behavior stay in `healthflow-agents`
(pinned v0.3.0). The server owns transport (HTTP), persistence, config, and
presentation only.

## Decisions already made

- **Hosting:** long-running host (Railway; Render/Fly equivalent shape).
  Not Vercel — batches are minutes-long sequential Claude calls.
- **Repo:** this repo. New `server/` beside `overturn/` (CLI, untouched)
  and `frontend/` (React app, gains an API mode).
- **Auth (Phase 1):** single admin login from env config + signed session
  cookie. Unauthenticated visitors get a read-only synthetic demo run.
- **Jobs:** Approach A — Postgres-backed queue with a dedicated worker
  process. No Redis/Celery in Phase 1; that is the documented Phase 2/3
  upgrade path if volume demands it.

## Architecture

One Docker image, two Railway services from it plus managed Postgres:

```
                    ┌────────────────────────┐
                    │   Postgres (managed)   │
                    │  runs · claims · audit │
                    └───────┬──────────┬─────┘
                            │          │
              ┌─────────────┴──┐   ┌───┴──────────────┐
              │  web service   │   │  worker service  │
              │ FastAPI /api/* │   │  queue loop:     │
              │ + serves SPA   │   │  claim run, draft│
              │   (dist-app)   │   │  appeals, update │
              └────────────────┘   │  progress        │
                                   └───────┬──────────┘
                                           │ AppealAgent (healthflow-agents)
                                           │ DbAuditSink / DbInvocationTracker
                                           ▼
                                      Anthropic API
```

Directory layout:

```
server/
  app.py            # FastAPI app factory, static SPA mounting
  api/              # routers: auth, runs, claims, demo
  db.py             # engine/session setup
  models.py         # SQLAlchemy models: Run, Claim, AuditEvent
  sinks.py          # DbAuditSink, DbInvocationTracker (package protocols)
  worker.py         # queue loop + per-record processing
  security.py       # admin credential check, session helpers
  config.py         # env-driven settings (pydantic-settings)
  migrations/       # alembic
```

## Data model (Postgres, SQLAlchemy + Alembic)

**runs**
- `id` (uuid pk), `filename`, `dry_run` (bool)
- `status`: `queued | running | completed | failed`
- `total_records`, `drafted`, `failed_records` (progress counters)
- `total_billed` (numeric)
- `error` (text, nullable — run-level failure reason)
- `created_at`, `started_at`, `finished_at`

**claims**
- `id` (uuid pk), `run_id` (fk, indexed)
- Remittance fields: `claim_id`, `payer`, `carc_code`, `rarc_codes` (jsonb),
  `billed_amount`, `service_date`, `denial_date`, `appeal_deadline`
  (nullable), `denial_reason_text`
- Pipeline outputs: `carc_text` (from DenialCodeDB at draft time), `letter`
  (current, editable), `letter_original` (for Revert), `refined`, `rule`,
  `error` (nullable)
- `status`: `queued | drafting | draft_ready | failed | submitted`
  (workbench displays Draft Ready / Failed / Submitted; `queued/drafting`
  are transient worker states)
- `updated_at`

**audit_events**
- `id` (bigserial pk), `run_id` (fk, indexed), `ts`
- `event_type`, `agent` (nullable), `model` (nullable), `duration_ms`
  (nullable), `error` (nullable), `details` (jsonb)

`DbAuditSink` and `DbInvocationTracker` implement the healthflow-agents
`AuditSink`/`InvocationTracker` protocols writing to `audit_events` — the
third real implementation of the injection pattern (stdout, JSONL, DB).
Same contract as the others: records written on success or error, exceptions
propagate, sink failures never break the wrapped operation.

No users table in Phase 1. Admin identity comes from env
(`ADMIN_EMAIL`, `ADMIN_PASSWORD`); the password is verified against a hash
computed at startup; sessions are signed cookies (Starlette
SessionMiddleware + `SECRET_KEY`).

## API (FastAPI, all under `/api/v1`)

Auth:
- `POST /auth/login` {email, password} → sets session cookie
- `POST /auth/logout`
- `GET /auth/me` → `{email}` or 401

Runs (auth required unless noted):
- `POST /runs` — multipart upload (.csv/.json, simplified-835 format) +
  `dry_run` flag. Validates with the package's remittance parser **at upload
  time**; a bad file is rejected 422 with the parser's row-numbered errors;
  a valid file creates the run (`queued`) and one claims row per record,
  then returns 202 `{run_id}`. Uploads exceeding `MAX_UPLOAD_RECORDS`
  (default 200) are rejected 413 — cost guard.
- `GET /runs` — list with status/counters, newest first
- `GET /runs/{id}` — status + progress counters (UI polls this ~every 2s;
  no SSE/websockets in Phase 1)
- `POST /runs/{id}/retry` — re-queues only claims not in
  `draft_ready/submitted` (crash/cost recovery; no automatic retries)
- `GET /runs/{id}/claims` — the worklist payload (same field shape as the
  static report's data island, so frontend components are reused untouched)
- `GET /runs/{id}/audit` — audit trail
- `GET /runs/{id}/letters.zip` — bulk letter export (server-side zip)

Claims:
- `GET /claims/{id}`
- `PATCH /claims/{id}` — body is one of `{letter}` (edit; server keeps
  `letter_original`), `{status: "submitted"}` (approve), or
  `{letter: null}` (revert to `letter_original`)
- `GET /claims/{id}/letter.md` — single letter download (letter + refined
  section, same markdown the CLI writes)

Demo (unauthenticated, read-only):
- `GET /demo/claims`, `GET /demo/audit` — serve a synthetic run seeded at
  startup (`make_synthetic_denials`, dry-run drafted) when `DEMO_MODE=1`.
  Write endpoints never accept the demo run's ids.

The SPA is served by the web service: `/` → `frontend/dist-app` static
files, with an SPA fallback for client routes. `/api/*` is JSON-only.

## Worker

`python -m server.worker` — a loop:

1. Claim the oldest `queued` run with
   `SELECT … FOR UPDATE SKIP LOCKED`; mark `running`, set `started_at`.
2. Build the agent once per run: `AppealAgent(audit_sink=DbAuditSink(run_id),
   invocation_tracker=DbInvocationTracker(run_id), client=DryRunClient() if
   dry_run else default)`.
3. For each claim in `queued` status (ordered by deadline urgency): mark
   `drafting`, call `agent.process_denial_record(record)`, persist outputs
   and `draft_ready` (or `failed` + error) **per claim**, update the run's
   progress counters in the same transaction. The claims table is the
   checkpoint: a worker crash loses at most the in-flight claim, and
   `/runs/{id}/retry` re-queues only unfinished ones.
4. When no claims remain queued/drafting: mark run `completed`
   (or `failed` if zero claims succeeded), set `finished_at`.

Rationale for per-record loop instead of the package's `BatchRunner`:
persistence-per-claim and crash resumability are transport concerns the
runner cannot provide (it returns results only at the end). The loop
contains no appeal logic — it is the CLI's iteration concern moved
server-side. Per-record failure isolation matches `BatchRunner`'s contract
(try/except per claim, never kills the batch).

Concurrency: one run at a time per worker process (matches the package's
`max_concurrency=1` constraint). Multiple workers would each claim distinct
runs safely via SKIP LOCKED, but Phase 1 deploys exactly one worker.

## Frontend

Two build targets from the one React codebase:
- `npm run build:template` — existing static-report build, **unchanged**.
  The CLI's `overturn report` keeps working exactly as today.
- `npm run build:app` — new SPA entry (`src/app/`) served by FastAPI.

SPA structure (no router library — screen state like the workbench today;
the URL hash carries the current run id, e.g. `#/runs/<id>`, so a refresh
returns to the same run):
- **Login screen** — email/password → `/auth/login`; unauthenticated users
  land on the read-only demo workbench with a "Sign in" affordance and the
  synthetic-data banner.
- **Runs screen** — upload control (file + dry-run toggle), list of runs
  with status and a progress bar (poll `GET /runs/{id}` while
  queued/running), link into each run's workbench.
- **Workbench screens** — the existing Worklist/Detail/Summary components
  reused as-is, fed by a data-source layer instead of the static island:
  `WorkbenchSource` interface with two implementations, `IslandSource`
  (today's behavior, used by the template build) and `ApiSource` (fetch +
  mutations). In API mode, Approve → `PATCH {status}`, letter edits →
  debounced `PATCH {letter}`, Revert → `PATCH {letter: null}`, exports hit
  the letter endpoints. The "(this session only)" label is removed in API
  mode; toasts reflect server confirmation.

## Config (env)

- `DATABASE_URL` (required)
- `ANTHROPIC_API_KEY` (required unless every run is dry-run)
- `ADMIN_EMAIL`, `ADMIN_PASSWORD` (required)
- `SECRET_KEY` (required — session signing)
- `MAX_UPLOAD_RECORDS` (default 200)
- `DEMO_MODE` (default 1 — seed and expose the public demo run)

## Safety and honesty rails

- Synthetic-data-only banner persists in the SPA; the upload screen states
  this is a demonstration system and real PHI must not be uploaded outside
  a BAA-covered deployment.
- Cost guards: record cap per upload, no automatic retries, dry-run toggle
  on every upload, API key never leaves the server.
- Audit trail is complete in the DB (redaction events included) and
  viewable per run in the workbench.

## Error handling

- Upload: parser errors → 422 with row numbers; oversized → 413; wrong
  extension → 415.
- Worker: per-claim failures recorded on the claim (`failed` + error),
  run continues; run-level crash leaves claims re-queueable via retry;
  worker marks a run `failed` with `error` when the file-level work is
  impossible (e.g., zero claims).
- API: 401 unauthenticated writes, 404 unknown ids, 409 for
  `PATCH` on claims of the demo run or of runs still `queued/drafting`.

## Testing

- **pytest (server/)**: API tests via FastAPI TestClient; worker tested by
  direct invocation with `DryRunClient`; DB is real Postgres via
  docker-compose (`docker compose up db`) — required because the queue uses
  `FOR UPDATE SKIP LOCKED`. Existing CLI tests untouched.
- **Vitest**: data-source layer (ApiSource with mocked fetch), Login and
  Runs screens, API-mode mutations on the workbench screens.
- **E2E (Playwright)**: one flow against a locally running server — login,
  upload a synthetic CSV as dry-run, poll to completion, open workbench,
  approve a claim, reload, assert the approval persisted.

## Deployment

- `Dockerfile` (multi-stage: node build of `dist-app` → python image with
  server + built SPA). `docker-compose.yml` for local dev (db + web +
  worker).
- Railway: two services from the same image — web (`uvicorn server.app`)
  and worker (`python -m server.worker`) — plus Postgres plugin. Alembic
  migrations run on web-service start.
- README gains a Deployment section.

## Out of scope (Phase 1)

Organizations/users/roles, billing, SSE/websockets, X12 835 parsing,
letter regeneration with new context, claim assignment, PHI/BAA
compliance work, queue infrastructure beyond Postgres (Redis/Celery),
horizontal worker scaling.
