# Phase 3 — Production Hardening (Spec Skeleton)

**Date:** 2026-07-12
**Status:** SKELETON — not yet brainstormed or approved. This document
collects the known Phase 3 scope so nothing is lost; each workstream gets
its own brainstorm → spec → plan cycle before any implementation.

## Goal

Take Overturn from a demo-grade multi-tenant SaaS (synthetic data, Railway,
hand-provisioned orgs) to a production-grade, PHI-capable product a billing
company could run its real denials through.

## The trigger

Most of this phase is **gated on the first customer who wants to process
real PHI**. Until then, Railway + synthetic/de-identified data is the right
posture (fastest iteration, lowest cost), and only Workstreams B and F
(incremental, portable) should proceed. Do not start Workstream A
speculatively.

---

## Workstream A — Compliance hosting migration (trigger-gated)

The BAA chain must cover every link: host, database, and LLM API.

- **Target:** GCP Cloud Run (web + worker, worker `min-instances=1`) +
  Cloud SQL Postgres, under Google's BAA. Fallback evaluated at decision
  time: AWS ECS Fargate + RDS; Aptible if we want compliance-PaaS
  hand-holding.
- **Anthropic BAA / zero-retention** for the API side. Interacts with the
  per-org BYO-key model: customer orgs must ALSO have their own BAA with
  Anthropic (or we proxy under ours — a real product decision to
  brainstorm: platform-billed LLM under our BAA vs per-org keys with
  per-org BAAs).
- Migration mechanics (deliberately easy — one image + Postgres + env):
  `pg_dump`/restore, same Docker image, six env vars, DNS cutover.
  Custom domain purchase happens here at the latest.
- CI/CD lands with it: GitHub Actions build → deploy (fixes the standing
  "pushes don't auto-deploy" gap permanently).
- Decommission checklist for Railway (secrets rotation on the way out).

## Workstream B — Security hardening pass (can start any time)

Accumulated from Phase 2 / dismiss / CSV-mapping reviews (ledger-sourced,
all currently triaged acceptable-for-now):

- Invite accept: row-lock (`with_for_update`) to close the double-use race;
  hash invite tokens at rest; stop tokens appearing in access logs (move
  token from URL path to request body on accept, or scrub logs).
- Login timing oracle: hash a dummy password when the email is unknown.
- Session hygiene: wrap `uuid.UUID(...)` parses (corrupt session → 401 not
  500); revisit cookie flags (SameSite, rotation on privilege change).
- Upload byte-size cap (the 413 guard is record-count only).
- `Content-Disposition` filename escaping for CSV-supplied claim ids.
- TOCTOU cleanups: `seed_demo` unique index on `is_demo`; admin create-org
  duplicate-name race (catch IntegrityError → 409); `upsert_csv_mapping`
  concurrent-insert race.
- Empty `PATCH /claims/{id}` body: 422 instead of 200 no-op.
- Worker resilience: exception guard + backoff in `run_worker_loop`,
  compose `restart:` policy.
- Self-host the Instrument Sans / Spline Sans Mono fonts (drop the Google
  Fonts CDN dependency — also a PHI-adjacent egress question).
- Dependency/report scrub: rate limiting on login and invite-accept.

## Workstream C — PHI data protection (trigger-gated, ships with A)

- Encryption at rest (Cloud SQL default; document key management; consider
  CMEK if a customer requires it).
- Access/audit logging for PHI reads (who viewed which claim when) — the
  audit_events table covers writes; reads are unlogged today.
- Data retention & deletion policy (org offboarding: today orgs can only
  be disabled, never deleted — deletion becomes a legal requirement).
- Backup/restore drill as a documented runbook (and PITR verification).
- De-identification guidance for design partners (what to strip before
  upload while pre-BAA).

## Workstream D — Denial workflow & outcomes (independent of trigger)

- Claim lifecycle beyond Submitted: `won | lost | partial` with recovered
  amount; outcome entry UI.
- Reporting: recovered dollars over time, win rate by payer/CARC, dismissal
  reasons breakdown (the data models already capture the inputs).
- Per-payer deadline overrides (payer → days table; supersedes the org
  default where present).
- Deadline notifications (needs an email provider decision — the same one
  unlocks emailed invites/password reset from Phase 2's deferred list).
- Claim assignment (which biller owns which claim).

## Workstream E — Billing (last)

- Plan model (per-seat vs per-claim vs flat), Stripe integration, usage
  metering per org (runs, claims drafted). Depends on real customer
  conversations; do not speculate before then.

## Workstream F — Engineering hygiene (can start any time)

- **CI on GitHub Actions** (currently everything runs locally): pytest with
  a Postgres service container, vitest, both builds, e2e against compose.
  Biggest bang-for-buck item in this whole document.
- Error tracking (Sentry) + uptime monitoring on the current deployment.
- Accepted code-quality minors from reviews (MappingPanel dedup, zero-count
  filter chips, fire-and-forget refetch, CARC-conflict RowNote, etc.) —
  batch as a cleanup task.

## Explicitly still out of scope

X12 835 parsing (healthflow-agents roadmap, separate session per house
rule), SSO/OAuth, org switcher UI, mobile, LLM-assisted column-mapping
suggestions.

## Suggested sequencing

1. **F (CI + monitoring)** — now; protects everything else.
2. **B (security pass)** — next quiet stretch; small, reviewable chunks.
3. **D (workflow/outcomes)** — when a design partner starts working real
   (de-identified) batches and wants outcome tracking.
4. **A + C together** — the day a customer says "real PHI"; brainstorm
   the platform-vs-per-org BAA question first, it shapes both.
5. **E (billing)** — when someone offers to pay.
