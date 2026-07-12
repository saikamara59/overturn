# CI/CD — Design

**Date:** 2026-07-12
**Status:** Approved (design discussion in session)

## Goal

Every PR and push to `main` runs the full test gate on GitHub Actions;
merges to `main` additionally deploy web + worker to Railway and smoke-check
the live site. This closes the standing "merges don't deploy" gap and puts
a machine gate where reviewer discipline currently stands.

## Workflow: `.github/workflows/ci.yml`

Triggers: `pull_request` (all branches) and `push` to `main`.
Concurrency: group by workflow+ref, `cancel-in-progress: true`.
All jobs `runs-on: ubuntu-latest` with explicit `timeout-minutes`.

### Job `backend` (timeout 15)
- Python **3.13** (production-image parity; local dev remains 3.14).
- Postgres 16 service container (`postgres:16-alpine`, health-checked,
  port 5432 exposed) with user/password/db `overturn` and a second database
  `overturn_test` created via an init step (`psql` createdb, since service
  containers don't run init scripts).
- `pip install -e ".[dev,server]"` (runner has git for the
  healthflow-agents git dependency).
- `TEST_DATABASE_URL=postgresql+psycopg://overturn:overturn@localhost:5432/overturn_test`
  `.venv-less` direct `pytest tests/ -q`.
- **Supporting code change:** `tests/server/conftest.py`'s
  unreachable-Postgres behavior becomes environment-aware — `pytest.skip`
  locally (unchanged DX), but `pytest.fail` with a clear message when
  `CI` env var is set, so a broken service container can never produce a
  silently-green run.

### Job `frontend` (timeout 10)
- Node 20, `npm ci` (cache npm), `npm test`, `npm run build:app`.
- Template-sync gate: `npm run build:template` then
  `git diff --exit-code overturn/templates/workbench.html` — mechanically
  enforces the "commit the rebuilt template with frontend source changes"
  README policy.

### Job `e2e` (timeout 20)
- `docker compose up -d --build` (compose file carries committed dev-only
  secrets; no CI configuration needed).
- Wait loop until `http://localhost:8000/api/v1/demo/claims` returns 200
  (bounded, with `docker compose logs` dumped on failure).
- `npm ci` in `frontend/`, `npx playwright install --with-deps chromium`,
  `npm run e2e` (3 specs; they are idempotent against a fresh DB by
  construction).
- On failure: upload `frontend/playwright-report/` as an artifact.

### Job `deploy` (main pushes only; `needs: [backend, frontend, e2e]`; timeout 15)
- Gated by `if: github.ref == 'refs/heads/main' && github.event_name == 'push'`.
- Install Railway CLI; auth via `RAILWAY_TOKEN` repository secret
  (project-scoped token the owner creates in the Railway dashboard — never
  passes through the assistant).
- `railway up --service web --detach` then `railway up --service worker
  --detach` from the checkout.
- Smoke check: bounded poll until the SPA (`/`) and
  `/api/v1/demo/claims` both return 200; fail the job (loudly) otherwise.
  Note: this validates liveness, not version — commit-hash version
  reporting is a future nicety, explicitly out of scope.

## Owner actions (documented in README)
1. Create a Railway **project token** (dashboard → project → Settings →
   Tokens) and store it: `gh secret set RAILWAY_TOKEN`.
2. Recommended: branch protection on `main` requiring the three CI checks.

## README
- CI badge at the top; short "CI/CD" subsection under Development
  describing the gate and the deploy-on-merge behavior; note that manual
  `railway up` remains available as a fallback.

## Testing the pipeline
The implementation lands on a branch and opens a PR — the PR run **is** the
test (all three CI jobs green on a real run). The deploy job is proven on
the subsequent merge to `main`, verified by the smoke check plus a manual
live probe. A deliberate failure check (e.g. a scratch commit with a
failing assertion, then reverted, or verification that a prior red run
blocks deploy) is included in the plan to prove the gate actually gates.

## Out of scope
Commit-version verification in the smoke check, coverage reporting, matrix
builds (3.13+3.14), Sentry/uptime monitoring (separate Phase 3 F item),
deploy previews, caching Docker layers for the e2e job.
