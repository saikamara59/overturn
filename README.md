# Overturn

Overturn is a provider-side denial management CLI: it ingests payer denial
remittances (simplified 835 CSV/JSON), runs each denied claim through the
[healthflow-agents](https://github.com/saikamara59/healthflow-agents) appeal
engine — PHI redaction, CARC/RARC code lookup, appeal-letter drafting, and
Claude-refined appeal recommendations — and produces a deadline-prioritized
worklist so an RCM team works the most urgent, highest-dollar appeals first.
Overturn itself is a thin adapter: transport, config, and presentation only.
All agent logic, redaction, safety behavior, and data contracts live in the
healthflow-agents package.

> **Demonstration system.** Overturn is not production RCM software. It ships
> with a synthetic-data generator and must only be run on synthetic data —
> real PHI must not be processed outside a BAA-covered deployment.

## Architecture

Overturn is one of two thin hosts over a shared agent package:

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
      │ (patient-side │            │ (provider-side│
      │    web app)   │            │     CLI)      │
      └───────────────┘            └───────────────┘
```

Both hosts inject their own implementations of the package's logging
protocols; Overturn's are JSONL file writers (`audit.jsonl` in each run's
output directory), demonstrating that the injection pattern works with a
second real implementation.

## Quickstart

```bash
pip install "git+https://github.com/saikamara59/overturn"   # or: pip install -e .
overturn demo
```

`overturn demo` needs zero setup and no API key: it generates 50 synthetic
denials, runs the full pipeline (redaction → parsing → code lookup → letter
drafting → prioritization), and prints the worklist plus one sample appeal
letter. Pass `--live` (with `ANTHROPIC_API_KEY` set) to add real Claude
refinement.

### Sample output

The Denial Workbench rendered from a 50-record synthetic batch
(`overturn run` → `overturn report`):

![Denial Workbench — prioritized worklist](docs/workbench-worklist.png)

## Commands

```bash
# Full pipeline over a remittance file (requires ANTHROPIC_API_KEY,
# or --dry-run to skip the LLM refinement step):
overturn run denials.csv --output-dir results [--limit N] [--json] [--dry-run]

# Batch stats from a prior run:
overturn summary results/worklist.json

# Interactive HTML Denial Workbench from a prior run (self-contained file):
overturn report results/ --open
```

`overturn report` renders the run into a single-file web workbench: a
filterable, sortable worklist; a claim-detail view showing the parsed denial
(CARC/RARC codes, redaction boundary) beside the editable drafted appeal
letter with export; and a batch-summary view with dollars-at-stake by CARC,
deadline distribution, and the full audit trail from `audit.jsonl`. Letter
edits and approvals in the workbench are session-local working state — the
files on disk are not modified.

![Denial Workbench — claim detail with drafted appeal](docs/workbench-detail.png)

![Denial Workbench — batch summary](docs/workbench-summary.png)

`overturn run` writes to the output directory:

- `worklist.json` — the full batch result plus priority order
- `appeals/<claim_id>.md` — one drafted appeal letter per record
- `audit.jsonl` — every audit event and agent invocation (including PHI
  redaction events), one JSON line each

Prioritization ranks by appeal-deadline proximity first (overdue claims at
the top, unknown deadlines last), then billed amount descending.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Tests stub the one LLM call through the package's supported `client=`
injection point; no network access or API key is required.

### Frontend (Denial Workbench)

The HTML workbench template is built from a React + TypeScript app in
`frontend/`. The built single-file template is committed at
`overturn/templates/workbench.html`, so Python users never need Node.

To change the workbench UI:

```bash
cd frontend
npm install
npm run dev             # hot-reload dev server with a synthetic fixture
npm test                # Vitest + React Testing Library
npm run build:template  # build and install overturn/templates/workbench.html
```

Commit the rebuilt template together with the frontend source change.

### Server (Denial Workbench as a web app)

Phase 1 single-tenant server: upload a remittance in the browser, appeals
draft in the background, and the workbench persists approvals and letter
edits. Synthetic data only — do not upload real PHI; this is a demonstration
system and deployments are not BAA-covered.

Local stack (API + worker + Postgres):

```bash
docker compose up --build
# open http://localhost:8000 — read-only demo; sign in with ADMIN_EMAIL/ADMIN_PASSWORD
```

Development without Docker:

```bash
docker compose up -d db
.venv/bin/pip install -e ".[dev,server]"
DATABASE_URL=postgresql+psycopg://overturn:overturn@localhost:5433/overturn \
  ADMIN_EMAIL=a@b.c ADMIN_PASSWORD=pw SECRET_KEY=dev \
  KEY_ENCRYPTION_SECRET=$(.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") \
  .venv/bin/uvicorn server.app:app --reload &
DATABASE_URL=... .venv/bin/python -m server.worker &
cd frontend && npm run dev:app   # Vite dev server proxying /api
```

Deploy (Railway): create a project with a Postgres plugin and two services
from this repo's Dockerfile — **web** (default) and **worker** (set
`SERVICE_ROLE=worker`; the image's CMD dispatches on it). Set on both:
`DATABASE_URL` (from the plugin), `ADMIN_EMAIL`, `ADMIN_PASSWORD`,
`SECRET_KEY`, `KEY_ENCRYPTION_SECRET` (required — a urlsafe-base64 32-byte
Fernet key, generate with the command above; encrypts each org's stored
Anthropic API key), `ANTHROPIC_API_KEY` (optional — dry runs work without
it), `MAX_UPLOAD_RECORDS` (default 200), `DEMO_MODE` (default 1),
`SECURE_COOKIES` (default 0 — recommend setting to 1 in production so
session cookies are sent `https_only`). Migrations run automatically when
the web service starts.

Multi-tenancy (Phase 2): the platform admin (`ADMIN_EMAIL`) provisions
organizations from the Admin screen and shares single-use invite links.
Each org brings its own Anthropic API key (stored encrypted with
`KEY_ENCRYPTION_SECRET`); orgs without a key run dry-run only. Data is
isolated per org.
