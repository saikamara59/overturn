# Overturn

![ci](https://github.com/saikamara59/overturn/actions/workflows/ci.yml/badge.svg)

**AI-assisted denial management for medical billing teams.** Overturn turns
payer denial remittances into a deadline-prioritized appeal worklist with
Claude-drafted appeal letters — so billers work the most urgent,
highest-dollar denials first and ship researched appeals in minutes instead
of half an hour each.

**Live demo:** https://overturn.up.railway.app — no signup needed; the
public view is a read-only workbench over 50 synthetic denials.

> **Demonstration system.** Overturn is not production RCM software. It ships
> with a synthetic-data generator and must only be run on synthetic or
> de-identified data — real PHI must not be processed outside a BAA-covered
> deployment.

## The problem

When an insurer denies a claim, the money usually isn't gone — most denials
are appealable, and appeals succeed often enough to be worth filing. But
writing one appeal means decoding CARC/RARC denial codes, finding the
regulatory counter-argument, and drafting a formal letter under a 30–90 day
deadline. Teams facing hundreds of denials cherry-pick a few and write off
the rest. Overturn exists to let the same team work the whole list.

## What it does

- **Upload real clearinghouse exports unchanged** — unknown CSV columns get
  an auto-suggested mapping (saved per organization), values are normalized
  (`$12,500.00`, `04/10/2026`, split CARC group/code columns), and missing
  appeal deadlines are computed from a per-org rule.
- **Deadline-first triage** — the worklist sorts by appeal deadline, then
  dollars at stake; overdue claims are flagged in red.
- **AI-drafted appeals, human-approved** — each denial gets a letter built
  from a curated CARC database (real CMS citations) plus a Claude-refined
  recommendation. Patient identifiers are redacted *before* any text
  reaches the model. Nothing is auto-submitted: a biller reviews, edits,
  and clicks Approve — or Dismisses with a reason, reversibly.
- **Multi-tenant** — the platform admin provisions organizations and shares
  single-use invite links; every org's data is hard-isolated, and each org
  brings its own Anthropic API key (Fernet-encrypted at rest), so AI costs
  bill to the tenant.
- **Complete audit trail** — every redaction, model call, draft, dismissal,
  and approval is recorded per run and visible in the workbench.

## Screenshots

The Denial Workbench — prioritized worklist, claim detail with the drafted
appeal, and batch summary:

![Denial Workbench — prioritized worklist](docs/workbench-worklist.png)

![Denial Workbench — claim detail with drafted appeal](docs/workbench-detail.png)

![Denial Workbench — batch summary](docs/workbench-summary.png)

## Architecture

Overturn is a **thin host** over a shared agent package — all appeal logic,
PHI redaction, prompts, and data contracts live in
[healthflow-agents](https://github.com/saikamara59/healthflow-agents);
Overturn owns transport, persistence, and presentation only:

```
                ┌─────────────────────────┐
                │    healthflow-agents    │   agents, contracts, redaction,
                │   (pip package, v0.3)   │   safety, prompts, batch engine
                └───────────┬─────────────┘
                            │  injected AuditSink / InvocationTracker
              ┌─────────────┴──────────────┐
              ▼                            ▼
      ┌───────────────┐            ┌───────────────┐
      │  healthflow   │            │   overturn    │
      │ (patient-side │            │  CLI + SaaS   │
      │    web app)   │            │  (this repo)  │
      └───────────────┘            └───────────────┘
```

Inside this repo:

- **`overturn/`** — the original CLI (`run` / `demo` / `summary` /
  `report`), which renders a fully self-contained single-file HTML
  workbench from any batch.
- **`server/`** — FastAPI web service + background worker sharing Postgres.
  **Postgres is the job queue** (`FOR UPDATE SKIP LOCKED`); the claims
  table doubles as a per-record checkpoint, so a crashed batch resumes
  without re-spending API calls.
- **`frontend/`** — one React 18 + TypeScript codebase with two build
  targets: the served SPA and the static report template embedded in the
  CLI (committed, so pip users never need Node).
- The package's logging interfaces are injected with three real
  implementations (stdout, JSONL files, Postgres) — the same agents run
  unchanged in every host.

**Stack:** Python / FastAPI / SQLAlchemy / Alembic / Postgres · React 18 /
TypeScript / Vite · Claude (Anthropic API) · Docker · Railway · GitHub
Actions.

## Engineering practices

- **~230 automated tests** across three layers: 155 pytest (API, worker,
  tenant isolation, ingestion engine — run against real Postgres), 69
  Vitest component/unit tests, and Playwright end-to-end flows (upload →
  background drafting → approval persisting across reload; multi-tenant
  onboarding; messy-CSV mapping).
- **CI/CD:** every PR runs backend, frontend, and E2E gates; merges to
  `main` auto-deploy web + worker to Railway and smoke-check the live
  site. The template build is verified in-sync on every PR.
- **Tenant isolation as a tested invariant:** cross-org access always
  returns 404 (never leaking existence), enforced by scoped dependencies
  and covered by a dedicated adversarial test suite.
- **Secrets hygiene:** org API keys are Fernet-encrypted under a deploy
  secret and surface only as a last-4 hint; sessions are signed cookies;
  misconfiguration fails loudly at boot with the offending variable named.
- **Spec-first workflow:** every feature in `docs/superpowers/specs/` and
  `docs/superpowers/plans/`, mirrored to Linear, implemented via
  test-driven tasks with independent review gates.

## Quickstart (CLI)

```bash
pip install "git+https://github.com/saikamara59/overturn"   # or: pip install -e .
overturn demo
```

`overturn demo` needs zero setup and no API key: it generates 50 synthetic
denials, runs the full pipeline (redaction → parsing → code lookup → letter
drafting → prioritization), and prints the worklist plus one sample appeal
letter. Pass `--live` (with `ANTHROPIC_API_KEY` set) to add real Claude
refinement.

## CLI commands

```bash
# Full pipeline over a remittance file (requires ANTHROPIC_API_KEY,
# or --dry-run to skip the LLM refinement step):
overturn run denials.csv --output-dir results [--limit N] [--json] [--dry-run]

# Batch stats from a prior run:
overturn summary results/worklist.json

# Interactive HTML Denial Workbench from a prior run (self-contained file):
overturn report results/ --open
```

`overturn run` writes to the output directory:

- `worklist.json` — the full batch result plus priority order
- `appeals/<claim_id>.md` — one drafted appeal letter per record
- `audit.jsonl` — every audit event and agent invocation (including PHI
  redaction events), one JSON line each

Prioritization ranks by appeal-deadline proximity first (overdue claims at
the top, unknown deadlines last), then billed amount descending.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev,server]"
docker compose up -d db     # server tests need Postgres (they skip without it)
.venv/bin/pytest
```

Tests stub the one LLM call through the package's supported `client=`
injection point; no network access or API key is required.

### Frontend (Denial Workbench)

The workbench UI is a React + TypeScript app in `frontend/` with two build
targets. The static template is committed at
`overturn/templates/workbench.html`, so Python users never need Node.

```bash
cd frontend
npm install
npm run dev             # static-report mode with a synthetic fixture
npm run dev:app         # SPA mode, proxying /api to localhost:8000
npm test                # Vitest + React Testing Library
npm run build:template  # build and install the committed template
npm run build:app       # build the served SPA
```

Commit the rebuilt template together with frontend source changes (CI
enforces this).

### Server (the SaaS)

Local stack (API + worker + Postgres):

```bash
docker compose up --build
# open http://localhost:8000 — read-only demo; sign in with ADMIN_EMAIL/ADMIN_PASSWORD
```

Development without Docker:

```bash
docker compose up -d db
DATABASE_URL=postgresql+psycopg://overturn:overturn@localhost:5433/overturn \
  ADMIN_EMAIL=a@b.c ADMIN_PASSWORD=pw SECRET_KEY=dev \
  KEY_ENCRYPTION_SECRET=$(.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") \
  .venv/bin/uvicorn server.app:app --reload &
DATABASE_URL=... .venv/bin/python -m server.worker &
cd frontend && npm run dev:app
```

Deploy (Railway): a Postgres plugin and two services from this repo's
Dockerfile — **web** (default) and **worker** (set `SERVICE_ROLE=worker`;
the image's CMD dispatches on it). Env on both: `DATABASE_URL`,
`ADMIN_EMAIL`, `ADMIN_PASSWORD`, `SECRET_KEY`, `KEY_ENCRYPTION_SECRET`
(required — a urlsafe-base64 32-byte Fernet key; encrypts each org's stored
Anthropic API key), `MAX_UPLOAD_RECORDS` (default 200), `DEMO_MODE`
(default 1), `SECURE_COOKIES` (set to 1 in production). Migrations run
automatically when the web service starts.

Multi-tenancy: the platform admin (`ADMIN_EMAIL`) provisions organizations
from the Admin screen and shares single-use invite links. Each org brings
its own Anthropic API key (stored encrypted); orgs without a key run
dry-run only. Data is isolated per org.

### CI/CD

Every PR runs three required gates on GitHub Actions: backend (pytest
against a Postgres service container), frontend (Vitest + both builds + the
committed-template sync check), and e2e (Playwright against the compose
stack). Merges to `main` additionally deploy web + worker to Railway (via
the `RAILWAY_TOKEN` repository secret) and smoke-check the live site.
Manual deploys remain available with `railway up --service web|worker`.
