# Overturn Server Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Single-tenant server core: upload remittance → Postgres-queued background pipeline → persistent worklist served to the React workbench as a real SPA with login.

**Architecture:** FastAPI web service (API + served SPA) and a worker process share one Postgres database; Postgres is the job queue (`FOR UPDATE SKIP LOCKED`). The worker drafts appeals per-claim via `AppealAgent.process_denial_record`, persisting each claim as a checkpoint. New `DbAuditSink`/`DbInvocationTracker` implement the healthflow-agents logging protocols against an `audit_events` table. The React app gains a second build target (SPA) that reuses the existing workbench components behind an API data layer with persistent mutations.

**Tech Stack:** FastAPI, SQLAlchemy 2 (typed ORM), Alembic, psycopg 3, pydantic-settings, Starlette sessions; React 18 + TS (existing); Docker + docker-compose; Railway deploy.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-06-server-phase1-design.md`. Server is a THIN HOST — no appeal logic, prompts, or redaction here; all of that stays in healthflow-agents v0.3.0.
- The CLI (`overturn/`), its tests (`tests/*.py` at top level), and the static-report build (`npm run build:template`, `overturn/templates/workbench.html`) must keep working unchanged.
- Server tests live in `tests/server/` and run against real Postgres (`docker compose up -d db`); if Postgres is unreachable they SKIP with a clear message, never fail.
- API JSON uses camelCase keys. Claim worklist entries use the exact static-report island field shape plus `dbId` (server uuid for mutations).
- Claim statuses in DB: `queued | drafting | draft_ready | failed | submitted`; displayed as `Queued | Drafting | Draft Ready | Failed | Submitted`.
- Cost guards: `MAX_UPLOAD_RECORDS` (default 200) rejects with 413; no automatic retries; live (non-dry-run) uploads rejected 422 when `ANTHROPIC_API_KEY` is unset.
- Demo run (`is_demo=True`) is world-readable, never writable (409 on PATCH).
- Env config (exact names): `DATABASE_URL`, `ANTHROPIC_API_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `SECRET_KEY`, `MAX_UPLOAD_RECORDS`, `DEMO_MODE`.
- Every commit message ends with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Python deps go in a `server` optional-dependency extra in `pyproject.toml`; install with `.venv/bin/pip install -e ".[dev,server]"`.

---

### Task 1: Server foundation — deps, config, DB engine, models, migrations, test harness

**Files:**
- Modify: `pyproject.toml` (add `server` extra)
- Create: `docker-compose.yml` (db service only for now; web/worker land in Task 10)
- Create: `docker/db-init.sql`
- Create: `server/__init__.py` (empty)
- Create: `server/config.py`
- Create: `server/db.py`
- Create: `server/models.py`
- Create: `alembic.ini`, `server/migrations/env.py`, `server/migrations/script.py.mako`, `server/migrations/versions/0001_initial.py`
- Create: `tests/server/__init__.py` (empty), `tests/server/conftest.py`
- Test: `tests/server/test_models.py`

**Interfaces:**
- Produces: `server.config.Settings` (fields: `database_url: str`, `anthropic_api_key: str | None`, `admin_email: str`, `admin_password: str`, `secret_key: str`, `max_upload_records: int = 200`, `demo_mode: bool = True`, `spa_dir: str | None = None`) and `get_settings()`.
- Produces: `server.db.make_engine(url)`, `server.db.make_session_factory(engine)` (sessionmaker, `expire_on_commit=False`).
- Produces: `server.models.Base`, `Run`, `Claim`, `AuditEvent`, `utcnow()`.
- Produces test fixtures in `tests/server/conftest.py`: `engine` (session-scoped, skips if Postgres down), `session_factory` (function-scoped; drops+creates all tables).

- [ ] **Step 1: Add the server extra and dev database**

In `pyproject.toml`, after the existing `[project.optional-dependencies]` `dev` line, extend the table:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0"]
server = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg[binary]>=3.2",
    "pydantic-settings>=2.4",
    "python-multipart>=0.0.9",
    "itsdangerous>=2.2",
]
```

`docker-compose.yml` (repo root):

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: overturn
      POSTGRES_PASSWORD: overturn
      POSTGRES_DB: overturn
    ports:
      - "5433:5432"
    volumes:
      - db-data:/var/lib/postgresql/data
      - ./docker/db-init.sql:/docker-entrypoint-initdb.d/db-init.sql
volumes:
  db-data:
```

`docker/db-init.sql`:

```sql
CREATE DATABASE overturn_test OWNER overturn;
```

Run: `.venv/bin/pip install -e ".[dev,server]" && docker compose up -d db`

- [ ] **Step 2: Write the failing model tests**

`tests/server/conftest.py`:

```python
"""Server test harness: real Postgres via docker compose (port 5433)."""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://overturn:overturn@localhost:5433/overturn_test",
)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip(
            "Postgres unreachable — start it with `docker compose up -d db`",
            allow_module_level=False,
        )
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    from server.models import Base

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
```

`tests/server/test_models.py`:

```python
from datetime import date

from server.models import AuditEvent, Claim, Run, utcnow


def make_run(**over):
    defaults = dict(filename="remit.csv", total_records=1, total_billed=100.5)
    defaults.update(over)
    return Run(**defaults)


def make_claim(run, **over):
    defaults = dict(
        run_id=run.id, claim_id="CLM-1", payer="P", carc_code="CO-50",
        rarc_codes=["N115"], billed_amount=100.5,
        service_date=date(2026, 5, 1), denial_date=date(2026, 6, 1),
        appeal_deadline=date(2026, 8, 1), denial_reason_text="text",
    )
    defaults.update(over)
    return Claim(**defaults)


def test_run_defaults_and_roundtrip(session_factory):
    with session_factory() as s:
        run = make_run()
        s.add(run)
        s.commit()
        assert run.status == "queued"
        assert run.dry_run is False and run.is_demo is False
        assert run.drafted == 0 and run.failed_records == 0
        assert run.created_at is not None and run.started_at is None


def test_claim_defaults_and_cascade_delete(session_factory):
    with session_factory() as s:
        run = make_run()
        s.add(run)
        s.flush()
        s.add(make_claim(run))
        s.commit()
        claim = s.query(Claim).one()
        assert claim.status == "queued"
        assert claim.rarc_codes == ["N115"]
        assert claim.letter is None and claim.letter_original is None
        s.delete(run)
        s.commit()
        assert s.query(Claim).count() == 0


def test_audit_event_jsonb_details(session_factory):
    with session_factory() as s:
        run = make_run()
        s.add(run)
        s.flush()
        s.add(AuditEvent(run_id=run.id, ts=utcnow(), event_type="phi_redacted",
                         details={"count": 2, "types": ["NAME"]}))
        s.commit()
        ev = s.query(AuditEvent).one()
        assert ev.details["count"] == 2
        assert ev.agent is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/server/ -q`
Expected: FAIL/ERROR — `server.models` does not exist. (If it SKIPs, start the db first.)

- [ ] **Step 4: Implement config, db, models**

`server/config.py`:

```python
"""Env-driven settings. Exact env names are part of the spec."""
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    anthropic_api_key: str | None = None
    admin_email: str
    admin_password: str
    secret_key: str
    max_upload_records: int = 200
    demo_mode: bool = True
    spa_dir: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`server/db.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
```

`server/models.py`:

```python
"""Persistence model: runs (the job queue), claims (per-denial checkpoint),
audit_events (DB implementation of the package's audit protocols)."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    filename: Mapped[str]
    dry_run: Mapped[bool] = mapped_column(default=False)
    is_demo: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(default="queued")
    total_records: Mapped[int] = mapped_column(default=0)
    drafted: Mapped[int] = mapped_column(default=0)
    failed_records: Mapped[int] = mapped_column(default=0)
    total_billed: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    claims: Mapped[list["Claim"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    claim_id: Mapped[str]
    payer: Mapped[str]
    carc_code: Mapped[str]
    rarc_codes: Mapped[list] = mapped_column(JSONB, default=list)
    billed_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    service_date: Mapped[date] = mapped_column(Date)
    denial_date: Mapped[date] = mapped_column(Date)
    appeal_deadline: Mapped[date | None] = mapped_column(Date, default=None)
    denial_reason_text: Mapped[str] = mapped_column(Text)
    carc_text: Mapped[str | None] = mapped_column(Text, default=None)
    letter: Mapped[str | None] = mapped_column(Text, default=None)
    letter_original: Mapped[str | None] = mapped_column(Text, default=None)
    refined: Mapped[str | None] = mapped_column(Text, default=None)
    rule: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(default="queued")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    run: Mapped[Run] = relationship(back_populates="claims")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event_type: Mapped[str]
    agent: Mapped[str | None] = mapped_column(default=None)
    model: Mapped[str | None] = mapped_column(default=None)
    duration_ms: Mapped[int | None] = mapped_column(default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
```

- [ ] **Step 5: Alembic setup and initial migration**

`alembic.ini` (repo root):

```ini
[alembic]
script_location = server/migrations

[loggers]
keys = root

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

`server/migrations/env.py`:

```python
import os

from alembic import context
from sqlalchemy import create_engine

from server.models import Base

config = context.config
target_metadata = Base.metadata


def get_url() -> str:
    return os.environ["DATABASE_URL"]


def run_migrations_offline() -> None:
    context.configure(url=get_url(), target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

`server/migrations/script.py.mako` — copy verbatim from Alembic's default template (`.venv/lib/python*/site-packages/alembic/templates/generic/script.py.mako`).

Generate the initial migration against the dev db (autogenerate is acceptable — review the output matches the three tables):

Run: `DATABASE_URL=postgresql+psycopg://overturn:overturn@localhost:5433/overturn .venv/bin/alembic revision --autogenerate -m "initial"`
Then rename the generated file to `server/migrations/versions/0001_initial.py` (keep its revision id) and: `DATABASE_URL=postgresql+psycopg://overturn:overturn@localhost:5433/overturn .venv/bin/alembic upgrade head`
Expected: tables created in the dev db.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/server/ -q`
Expected: 3 passed. Also run `.venv/bin/python -m pytest tests/ -q` — the existing 34 CLI tests must still pass (35 total files now; expect 37 passed).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml docker-compose.yml docker/ server/ alembic.ini tests/server/
git commit -m "server: foundation — config, models, migrations, Postgres test harness"
```

---

### Task 2: DB audit sinks (third implementation of the injection pattern)

**Files:**
- Create: `server/sinks.py`
- Test: `tests/server/test_sinks.py`

**Interfaces:**
- Consumes: `server.models.AuditEvent`, `utcnow`; sessionmaker from Task 1.
- Produces: `DbAuditSink(session_factory, run_id)` with `.log(event_type: str, details: dict) -> None`; `DbInvocationTracker(session_factory, run_id)` callable as `tracker(agent=..., event_type=..., model=...)` context manager yielding a record with mutable `.details`. Both satisfy the healthflow-agents protocols; writes go to `audit_events`; sink failures never raise; body exceptions propagate and are recorded.

- [ ] **Step 1: Write the failing tests**

`tests/server/test_sinks.py`:

```python
import pytest
from healthflow_agents.core.logging import AuditSink

from server.models import AuditEvent, Run
from server.sinks import DbAuditSink, DbInvocationTracker


@pytest.fixture()
def run_id(session_factory):
    with session_factory() as s:
        run = Run(filename="f.csv")
        s.add(run)
        s.commit()
        return run.id


def events(session_factory):
    with session_factory() as s:
        return s.query(AuditEvent).order_by(AuditEvent.id).all()


def test_satisfies_protocol_and_writes_rows(session_factory, run_id):
    sink = DbAuditSink(session_factory, run_id)
    assert isinstance(sink, AuditSink)
    sink.log("phi_redacted", {"count": 2})
    sink.log("batch_started", {"records": 5})
    evs = events(session_factory)
    assert [e.event_type for e in evs] == ["phi_redacted", "batch_started"]
    assert evs[0].details == {"count": 2}


def test_non_json_details_are_stringified(session_factory, run_id):
    from datetime import date

    DbAuditSink(session_factory, run_id).log("e", {"when": date(2026, 7, 8)})
    assert events(session_factory)[0].details["when"] == "2026-07-08"


def test_tracker_records_success(session_factory, run_id):
    tracker = DbInvocationTracker(session_factory, run_id)
    with tracker(agent="appeal", event_type="process_denial_record", model="m1") as inv:
        inv.details = {"code": "CO-50"}
    (ev,) = events(session_factory)
    assert ev.event_type == "agent_invocation"
    assert ev.agent == "appeal"
    assert ev.model == "m1"
    assert ev.details["invocation_type"] == "process_denial_record"
    assert ev.details["code"] == "CO-50"
    assert ev.error is None and isinstance(ev.duration_ms, int)


def test_tracker_records_error_and_propagates(session_factory, run_id):
    tracker = DbInvocationTracker(session_factory, run_id)
    with pytest.raises(ValueError, match="boom"):
        with tracker(agent="appeal", event_type="run"):
            raise ValueError("boom")
    (ev,) = events(session_factory)
    assert ev.error == "ValueError: boom"


def test_sink_failure_never_breaks_caller(run_id):
    def broken_factory():
        raise RuntimeError("db down")

    DbAuditSink(broken_factory, run_id).log("e", {})  # must not raise
    tracker = DbInvocationTracker(broken_factory, run_id)
    with tracker(agent="a", event_type="t") as inv:
        inv.details = {"ok": True}  # must complete without raising
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/server/test_sinks.py -q`
Expected: FAIL — `server.sinks` missing.

- [ ] **Step 3: Implement**

`server/sinks.py`:

```python
"""DB implementations of healthflow-agents' AuditSink / InvocationTracker.

Third real implementation of the injection pattern (stdout, JSONL, now DB).
Contract parity: invocation rows are written on success or error, body
exceptions propagate, and failures inside the sink never break the caller.
Each write uses its own short-lived session so it cannot interfere with the
worker's claim transaction.
"""
import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from server.models import AuditEvent, utcnow


def _jsonable(details: dict) -> dict:
    return json.loads(json.dumps(details, default=str))


class DbAuditSink:
    def __init__(self, session_factory: Callable, run_id: uuid.UUID) -> None:
        self.session_factory = session_factory
        self.run_id = run_id

    def log(self, event_type: str, details: dict) -> None:
        try:
            with self.session_factory() as session:
                session.add(AuditEvent(
                    run_id=self.run_id, ts=utcnow(),
                    event_type=event_type, details=_jsonable(details),
                ))
                session.commit()
        except Exception:
            pass


@dataclass
class _InvocationRecord:
    details: dict[str, Any] = field(default_factory=dict)


class DbInvocationTracker:
    def __init__(self, session_factory: Callable, run_id: uuid.UUID) -> None:
        self.session_factory = session_factory
        self.run_id = run_id

    @contextmanager
    def __call__(
        self, *, agent: str, event_type: str, model: str | None = None
    ) -> Iterator[_InvocationRecord]:
        record = _InvocationRecord()
        error: str | None = None
        start = time.monotonic()
        try:
            yield record
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"[:512]
            raise
        finally:
            try:
                with self.session_factory() as session:
                    session.add(AuditEvent(
                        run_id=self.run_id, ts=utcnow(),
                        event_type="agent_invocation", agent=agent, model=model,
                        duration_ms=int((time.monotonic() - start) * 1000),
                        error=error,
                        details=_jsonable(
                            {"invocation_type": event_type, **record.details}
                        ),
                    ))
                    session.commit()
            except Exception:
                pass
```

- [ ] **Step 4: Run to verify pass; commit**

Run: `.venv/bin/python -m pytest tests/server/ -q` — expected all pass.

```bash
git add server/sinks.py tests/server/test_sinks.py
git commit -m "server: DbAuditSink and DbInvocationTracker (package logging protocols on Postgres)"
```

---

### Task 3: App factory, sessions, admin auth

**Files:**
- Create: `server/security.py`
- Create: `server/api/__init__.py` (empty)
- Create: `server/api/deps.py`
- Create: `server/api/auth.py`
- Create: `server/app.py`
- Test: `tests/server/test_auth.py`
- Modify: `tests/server/conftest.py` (add `client` fixture)

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: `server.app.create_app(settings: Settings, session_factory) -> FastAPI` (test-injectable; production entry `server.app:app` builds from env). `server.api.deps.get_session` (yields a Session, commits on success, rolls back on error) and `require_user(request) -> str` (401 when unauthenticated). Routes: `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`. Test fixtures: `settings` and `client` (authenticated helper `client.login()` not needed — tests post to login).

- [ ] **Step 1: Extend conftest and write failing auth tests**

Append to `tests/server/conftest.py`:

```python
@pytest.fixture()
def settings():
    from server.config import Settings

    return Settings(
        database_url=TEST_DATABASE_URL,
        admin_email="admin@example.com",
        admin_password="hunter2hunter2",
        secret_key="test-secret",
        anthropic_api_key=None,
        demo_mode=False,
    )


@pytest.fixture()
def client(settings, session_factory):
    from fastapi.testclient import TestClient

    from server.app import create_app

    app = create_app(settings=settings, session_factory=session_factory)
    with TestClient(app) as c:
        yield c


def login(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "hunter2hunter2"},
    )
    assert r.status_code == 200, r.text
```

`tests/server/test_auth.py`:

```python
from tests.server.conftest import login


def test_me_unauthenticated_is_401(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_success_sets_session(client):
    login(client)
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.json() == {"email": "admin@example.com"}


def test_login_wrong_password_is_401(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "wrong"},
    )
    assert r.status_code == 401


def test_logout_clears_session(client):
    login(client)
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").status_code == 401
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/server/test_auth.py -q`
Expected: FAIL — `server.app` missing.

- [ ] **Step 3: Implement**

`server/security.py`:

```python
import hashlib
import hmac

from fastapi import HTTPException, Request


def constant_time_equals(supplied: str, expected: str) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(supplied.encode()).digest(),
        hashlib.sha256(expected.encode()).digest(),
    )


def require_user(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="authentication required")
    return user
```

`server/api/deps.py`:

```python
from typing import Iterator

from fastapi import Request
from sqlalchemy.orm import Session


def get_session(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

`server/api/auth.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from server.security import constant_time_equals, require_user

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(request: Request, body: LoginBody) -> dict:
    settings = request.app.state.settings
    ok = (
        constant_time_equals(body.email, settings.admin_email)
        and constant_time_equals(body.password, settings.admin_password)
    )
    if not ok:
        raise HTTPException(status_code=401, detail="invalid credentials")
    request.session["user"] = body.email
    return {"email": body.email}


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(user: str = Depends(require_user)) -> dict:
    return {"email": user}
```

`server/app.py`:

```python
"""FastAPI app factory. Production entry: `uvicorn server.app:app`."""
from pathlib import Path

from fastapi import APIRouter, FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from server.api import auth
from server.config import Settings, get_settings
from server.db import make_engine, make_session_factory


def create_app(settings: Settings, session_factory) -> FastAPI:
    app = FastAPI(title="Overturn", version="0.1.0")
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

    api = APIRouter(prefix="/api/v1")
    api.include_router(auth.router)
    app.include_router(api)

    spa_dir = Path(settings.spa_dir) if settings.spa_dir else (
        Path(__file__).resolve().parent.parent / "frontend" / "dist-app"
    )
    if spa_dir.is_dir():
        app.mount("/", StaticFiles(directory=spa_dir, html=True), name="spa")
    return app


def build_app() -> FastAPI:
    settings = get_settings()
    return create_app(
        settings=settings,
        session_factory=make_session_factory(make_engine(settings.database_url)),
    )


app = None  # populated lazily for uvicorn: `uvicorn server.app:app --factory` not needed
try:  # pragma: no cover - production path only
    app = build_app()
except Exception:  # missing env in dev/test contexts is fine; tests use create_app
    app = None
```

Note: the module-level `app` builds only when env is configured (production
containers). Tests always call `create_app` directly.

- [ ] **Step 4: Run to verify pass; commit**

Run: `.venv/bin/python -m pytest tests/server/ -q` — all pass.

```bash
git add server/ tests/server/
git commit -m "server: app factory, session middleware, single-admin auth"
```

---

### Task 4: Runs API — upload, list, get, retry

**Files:**
- Create: `server/api/runs.py`
- Create: `server/payloads.py`
- Modify: `server/app.py` (include runs router)
- Test: `tests/server/test_runs_api.py`

**Interfaces:**
- Consumes: Tasks 1–3; `healthflow_agents.tools.remittance_parser` (`parse_remittance_csv/json`, `RemittanceParseError`).
- Produces: `server.payloads.run_payload(run) -> dict` (camelCase: `id, filename, dryRun, isDemo, status, totalRecords, drafted, failedRecords, totalBilled, error, createdAt, startedAt, finishedAt`). Routes: `POST /api/v1/runs` (202 → `{runId}`), `GET /api/v1/runs`, `GET /api/v1/runs/{run_id}`, `POST /api/v1/runs/{run_id}/retry` (→ `{requeued: n}`). Also exports `SAMPLE_CSV`-compatible upload helper for tests.

- [ ] **Step 1: Write the failing tests**

`tests/server/test_runs_api.py`:

```python
import io

from server.models import Claim, Run
from tests.conftest import SAMPLE_CSV  # 3 claims: CLM-001/002/003
from tests.server.conftest import login


def upload(client, *, content=SAMPLE_CSV, name="denials.csv", dry_run=True):
    return client.post(
        "/api/v1/runs",
        files={"file": (name, io.BytesIO(content.encode()), "text/csv")},
        data={"dry_run": "true" if dry_run else "false"},
    )


def test_upload_requires_auth(client):
    assert upload(client).status_code == 401


def test_upload_creates_run_and_claims(client, session_factory):
    login(client)
    r = upload(client)
    assert r.status_code == 202, r.text
    run_id = r.json()["runId"]
    with session_factory() as s:
        run = s.query(Run).one()
        assert str(run.id) == run_id
        assert run.status == "queued" and run.dry_run is True
        assert run.total_records == 3
        assert float(run.total_billed) == 21230.25
        claims = s.query(Claim).order_by(Claim.claim_id).all()
        assert [c.claim_id for c in claims] == ["CLM-001", "CLM-002", "CLM-003"]
        assert all(c.status == "queued" for c in claims)


def test_upload_rejects_bad_rows_with_422(client):
    login(client)
    bad = SAMPLE_CSV.replace("12500.00", "not-a-number")
    r = upload(client, content=bad)
    assert r.status_code == 422
    assert "row 0" in r.json()["detail"]


def test_upload_rejects_wrong_extension_415(client):
    login(client)
    assert upload(client, name="denials.txt").status_code == 415


def test_upload_record_cap_413(client, settings):
    login(client)
    header, row = SAMPLE_CSV.split("\n", 1)[0], SAMPLE_CSV.splitlines()[1]
    big = header + "\n" + "\n".join(
        row.replace("CLM-001", f"CLM-{i:04d}") for i in range(settings.max_upload_records + 1)
    )
    assert upload(client, content=big).status_code == 413


def test_live_upload_without_api_key_422(client):
    login(client)
    r = upload(client, dry_run=False)
    assert r.status_code == 422
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_list_and_get_runs(client):
    login(client)
    run_id = upload(client).json()["runId"]
    listed = client.get("/api/v1/runs").json()
    assert len(listed) == 1 and listed[0]["id"] == run_id
    got = client.get(f"/api/v1/runs/{run_id}").json()
    assert got["status"] == "queued"
    assert got["totalRecords"] == 3 and got["drafted"] == 0
    assert client.get("/api/v1/runs/00000000-0000-0000-0000-000000000000").status_code == 404


def test_retry_requeues_unfinished_claims(client, session_factory):
    login(client)
    run_id = upload(client).json()["runId"]
    with session_factory() as s:
        claims = s.query(Claim).order_by(Claim.claim_id).all()
        claims[0].status = "draft_ready"
        claims[1].status = "failed"
        claims[2].status = "drafting"
        run = s.query(Run).one()
        run.status = "failed"
        s.commit()
    r = client.post(f"/api/v1/runs/{run_id}/retry")
    assert r.status_code == 200 and r.json() == {"requeued": 2}
    with session_factory() as s:
        statuses = {c.claim_id: c.status for c in s.query(Claim).all()}
        assert statuses["CLM-001"] == "draft_ready"
        assert statuses["CLM-002"] == "queued" and statuses["CLM-003"] == "queued"
        assert s.query(Run).one().status == "queued"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/server/test_runs_api.py -q`
Expected: FAIL — routes missing (404s / import errors).

- [ ] **Step 3: Implement**

`server/payloads.py`:

```python
"""JSON payload builders. camelCase keys; claim entries reuse the static
report's island shape (see Task 6) so workbench components work unchanged."""
from server.models import Run


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def run_payload(run: Run) -> dict:
    return {
        "id": str(run.id),
        "filename": run.filename,
        "dryRun": run.dry_run,
        "isDemo": run.is_demo,
        "status": run.status,
        "totalRecords": run.total_records,
        "drafted": run.drafted,
        "failedRecords": run.failed_records,
        "totalBilled": float(run.total_billed),
        "error": run.error,
        "createdAt": _iso(run.created_at),
        "startedAt": _iso(run.started_at),
        "finishedAt": _iso(run.finished_at),
    }
```

`server/api/runs.py`:

```python
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from healthflow_agents.tools.remittance_parser import (
    RemittanceParseError,
    parse_remittance_csv,
    parse_remittance_json,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.api.deps import get_session
from server.models import Claim, Run
from server.payloads import run_payload
from server.security import require_user

router = APIRouter(prefix="/runs", tags=["runs"])


def get_run_or_404(session: Session, run_id: uuid.UUID) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.post("", status_code=202)
async def create_run(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Form(False),
    session: Session = Depends(get_session),
    _user: str = Depends(require_user),
) -> dict:
    settings = request.app.state.settings
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".csv", ".json"):
        raise HTTPException(415, detail=f"unsupported file type {suffix!r} (use .csv or .json)")

    text = (await file.read()).decode("utf-8", errors="replace")
    try:
        records = (
            parse_remittance_csv(text) if suffix == ".csv" else parse_remittance_json(text)
        )
    except RemittanceParseError as exc:
        raise HTTPException(422, detail=str(exc))
    except ValueError as exc:  # includes json.JSONDecodeError
        raise HTTPException(422, detail=f"could not parse file: {exc}")
    if not records:
        raise HTTPException(422, detail="file contains no denial records")
    if len(records) > settings.max_upload_records:
        raise HTTPException(
            413,
            detail=(
                f"{len(records)} records exceeds the per-upload cap of "
                f"{settings.max_upload_records}"
            ),
        )
    if not dry_run and not settings.anthropic_api_key:
        raise HTTPException(
            422,
            detail="ANTHROPIC_API_KEY is not configured on this server; upload with dry_run",
        )

    run = Run(
        filename=file.filename or "upload",
        dry_run=dry_run,
        total_records=len(records),
        total_billed=round(sum(r.billed_amount for r in records), 2),
    )
    session.add(run)
    session.flush()
    for r in records:
        session.add(Claim(
            run_id=run.id, claim_id=r.claim_id, payer=r.payer,
            carc_code=r.carc_code, rarc_codes=list(r.rarc_codes),
            billed_amount=r.billed_amount, service_date=r.service_date,
            denial_date=r.denial_date, appeal_deadline=r.appeal_deadline,
            denial_reason_text=r.denial_reason_text,
        ))
    return {"runId": str(run.id)}


@router.get("")
def list_runs(
    session: Session = Depends(get_session),
    _user: str = Depends(require_user),
) -> list[dict]:
    runs = session.scalars(select(Run).order_by(Run.created_at.desc())).all()
    return [run_payload(r) for r in runs]


@router.get("/{run_id}")
def get_run(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    _user: str = Depends(require_user),
) -> dict:
    return run_payload(get_run_or_404(session, run_id))


@router.post("/{run_id}/retry")
def retry_run(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    _user: str = Depends(require_user),
) -> dict:
    run = get_run_or_404(session, run_id)
    if run.is_demo:
        raise HTTPException(409, detail="demo run is read-only")
    requeued = 0
    for claim in run.claims:
        if claim.status not in ("draft_ready", "submitted"):
            claim.status = "queued"
            claim.error = None
            requeued += 1
    if requeued:
        run.status = "queued"
        run.error = None
        run.finished_at = None
    return {"requeued": requeued}
```

In `server/app.py`, import and include the router next to auth:

```python
from server.api import auth, runs
...
    api.include_router(auth.router)
    api.include_router(runs.router)
```

- [ ] **Step 4: Run to verify pass; commit**

Run: `.venv/bin/python -m pytest tests/server/ -q` — all pass. Also `.venv/bin/python -m pytest tests/ -q` (CLI suite unaffected).

```bash
git add server/ tests/server/test_runs_api.py
git commit -m "server: runs API — validated upload, list/get, manual retry"
```

---

### Task 5: Worker — Postgres queue loop with per-claim checkpointing

**Files:**
- Create: `server/worker.py`
- Test: `tests/server/test_worker.py`

**Interfaces:**
- Consumes: Tasks 1–2; `overturn.dryrun.DryRunClient`; `healthflow_agents` (`AppealAgent`, `DenialRecord`, `DenialCodeDB`).
- Produces: `claim_next_run(session) -> uuid.UUID | None`; `process_run(run_id, *, session_factory, client=None) -> None`; `run_worker_loop(session_factory, *, poll_interval=2.0, max_iterations=None)`; `python -m server.worker` entrypoint.

- [ ] **Step 1: Write the failing tests**

`tests/server/test_worker.py`:

```python
from datetime import date
from types import SimpleNamespace

import pytest
from healthflow_agents.tools.remittance_parser import make_synthetic_denials

from overturn.dryrun import DRY_RUN_NOTE, DryRunClient
from server.models import AuditEvent, Claim, Run
from server.worker import claim_next_run, process_run, run_worker_loop


def seed_run(session_factory, n=3, **run_over):
    records = make_synthetic_denials(n, seed=7, base_date=date(2026, 7, 8))
    with session_factory() as s:
        run = Run(filename="r.csv", dry_run=True, total_records=n,
                  total_billed=round(sum(r.billed_amount for r in records), 2),
                  **run_over)
        s.add(run)
        s.flush()
        for r in records:
            s.add(Claim(
                run_id=run.id, claim_id=r.claim_id, payer=r.payer,
                carc_code=r.carc_code, rarc_codes=list(r.rarc_codes),
                billed_amount=r.billed_amount, service_date=r.service_date,
                denial_date=r.denial_date, appeal_deadline=r.appeal_deadline,
                denial_reason_text=r.denial_reason_text,
            ))
        s.commit()
        return run.id


def test_claim_next_run_claims_oldest_and_marks_running(session_factory):
    run_id = seed_run(session_factory)
    with session_factory() as s:
        assert claim_next_run(s) == run_id
    with session_factory() as s:
        assert s.get(Run, run_id).status == "running"
        assert s.get(Run, run_id).started_at is not None
        assert claim_next_run(s) is None  # nothing left queued


def test_claim_next_run_skips_demo_runs(session_factory):
    seed_run(session_factory, is_demo=True)
    with session_factory() as s:
        assert claim_next_run(s) is None


def test_process_run_drafts_all_claims_and_updates_counters(session_factory):
    run_id = seed_run(session_factory)
    with session_factory() as s:
        claim_next_run(s)
    process_run(run_id, session_factory=session_factory, client=DryRunClient())
    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == "completed"
        assert run.drafted == 3 and run.failed_records == 0
        assert run.finished_at is not None
        for c in s.query(Claim).all():
            assert c.status == "draft_ready"
            assert c.letter and c.letter == c.letter_original
            assert c.refined == DRY_RUN_NOTE
            assert c.rule
        assert s.query(AuditEvent).filter_by(event_type="agent_invocation").count() >= 3


def test_process_run_isolates_failures_per_claim(session_factory):
    run_id = seed_run(session_factory)

    class ExplodingClient:
        calls = 0

        @property
        def messages(self):
            outer = self

            class M:
                def create(self, **kwargs):
                    outer.calls += 1
                    if outer.calls == 1:
                        raise RuntimeError("api down")
                    return SimpleNamespace(
                        content=[SimpleNamespace(text="refined")]
                    )
            return M()

    with session_factory() as s:
        claim_next_run(s)
    process_run(run_id, session_factory=session_factory, client=ExplodingClient())
    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == "completed"          # some succeeded
        assert run.drafted == 2 and run.failed_records == 1
        failed = [c for c in s.query(Claim).all() if c.status == "failed"]
        assert len(failed) == 1 and "RuntimeError" in failed[0].error


def test_process_run_all_failures_marks_run_failed(session_factory):
    run_id = seed_run(session_factory, n=2)

    class AlwaysBroken:
        @property
        def messages(self):
            class M:
                def create(self, **kwargs):
                    raise RuntimeError("no")
            return M()

    with session_factory() as s:
        claim_next_run(s)
    process_run(run_id, session_factory=session_factory, client=AlwaysBroken())
    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == "failed"
        assert run.failed_records == 2


def test_worker_loop_processes_queued_run(session_factory):
    run_id = seed_run(session_factory)
    run_worker_loop(
        session_factory, poll_interval=0.01, max_iterations=3,
        client=DryRunClient(),
    )
    with session_factory() as s:
        assert s.get(Run, run_id).status == "completed"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/server/test_worker.py -q`
Expected: FAIL — `server.worker` missing.

- [ ] **Step 3: Implement**

`server/worker.py`:

```python
"""Worker: Postgres-backed queue loop.

Claims one queued run at a time (FOR UPDATE SKIP LOCKED — multiple workers
never double-claim), then drafts appeals claim-by-claim, committing after
every claim so the claims table is the checkpoint: a crash loses at most the
in-flight claim, and /runs/{id}/retry re-queues only unfinished ones.

Thin-host note: the per-record loop is transport (persistence + progress);
all appeal logic is inside AppealAgent.process_denial_record. Per-record
failure isolation mirrors the package BatchRunner's contract.
"""
import time
import uuid
from typing import Callable

from healthflow_agents import AppealAgent
from healthflow_agents.contracts.denial_record import DenialRecord
from healthflow_agents.tools.denial_codes import DenialCodeDB
from sqlalchemy import select
from sqlalchemy.orm import Session

from overturn.dryrun import DryRunClient
from server.models import Claim, Run, utcnow
from server.sinks import DbAuditSink, DbInvocationTracker

POLL_INTERVAL_SECONDS = 2.0


def claim_next_run(session: Session) -> uuid.UUID | None:
    run = session.execute(
        select(Run)
        .where(Run.status == "queued", Run.is_demo.is_(False))
        .order_by(Run.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if run is None:
        return None
    run.status = "running"
    run.started_at = utcnow()
    session.commit()
    return run.id


def _build_agent(run: Run, session_factory: Callable, client=None) -> AppealAgent:
    kwargs: dict = {
        "audit_sink": DbAuditSink(session_factory, run.id),
        "invocation_tracker": DbInvocationTracker(session_factory, run.id),
    }
    if client is not None:
        kwargs["client"] = client
    elif run.dry_run:
        kwargs["client"] = DryRunClient()
    return AppealAgent(**kwargs)


def _record_for(claim: Claim) -> DenialRecord:
    return DenialRecord(
        claim_id=claim.claim_id,
        payer=claim.payer,
        carc_code=claim.carc_code,
        rarc_codes=list(claim.rarc_codes or []),
        denial_reason_text=claim.denial_reason_text,
        billed_amount=float(claim.billed_amount),
        service_date=claim.service_date,
        denial_date=claim.denial_date,
        appeal_deadline=claim.appeal_deadline,
    )


def process_run(
    run_id: uuid.UUID, *, session_factory: Callable, client=None
) -> None:
    code_db = DenialCodeDB()
    with session_factory() as session:
        run = session.get(Run, run_id)
        if run is None:
            return
        agent = _build_agent(run, session_factory, client)

        while True:
            claim = session.execute(
                select(Claim)
                .where(Claim.run_id == run_id, Claim.status == "queued")
                .order_by(
                    Claim.appeal_deadline.asc().nulls_last(),
                    Claim.billed_amount.desc(),
                )
                .limit(1)
            ).scalar_one_or_none()
            if claim is None:
                break
            claim.status = "drafting"
            session.commit()

            try:
                _analysis, argument, letter, refined = (
                    agent.process_denial_record(_record_for(claim))
                )
            except Exception as exc:
                claim.status = "failed"
                claim.error = f"{type(exc).__name__}: {exc}"[:512]
                run.failed_records += 1
            else:
                entry = code_db.lookup(claim.carc_code)
                claim.carc_text = entry["description"] if entry else None
                claim.letter = letter
                claim.letter_original = letter
                claim.refined = refined
                claim.rule = argument.cms_rule
                claim.status = "draft_ready"
                run.drafted += 1
            claim.updated_at = utcnow()
            session.commit()

        run.status = (
            "completed" if run.drafted > 0 or run.total_records == 0 else "failed"
        )
        if run.status == "failed":
            run.error = "all records failed"
        run.finished_at = utcnow()
        session.commit()


def run_worker_loop(
    session_factory: Callable,
    *,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    max_iterations: int | None = None,
    client=None,
) -> None:
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        with session_factory() as session:
            run_id = claim_next_run(session)
        if run_id is not None:
            process_run(run_id, session_factory=session_factory, client=client)
        else:
            time.sleep(poll_interval)


def main() -> None:  # pragma: no cover - production entrypoint
    from server.config import get_settings
    from server.db import make_engine, make_session_factory

    settings = get_settings()
    factory = make_session_factory(make_engine(settings.database_url))
    print("overturn worker: polling for queued runs")
    run_worker_loop(factory)


if __name__ == "__main__":  # pragma: no cover
    main()
```

- [ ] **Step 4: Run to verify pass; commit**

Run: `.venv/bin/python -m pytest tests/server/ -q` — all pass.

```bash
git add server/worker.py tests/server/test_worker.py
git commit -m "server: worker — SKIP LOCKED queue, per-claim checkpointed drafting"
```

---

### Task 6: Claims API + worklist/audit payloads + letter exports

**Files:**
- Create: `server/api/claims.py`
- Modify: `server/payloads.py` (add `claim_entry`, `worklist_payload`, `audit_entries`, `letter_markdown`)
- Modify: `server/api/runs.py` (add `/runs/{id}/claims`, `/runs/{id}/audit`, `/runs/{id}/letters.zip`)
- Modify: `server/app.py` (include claims router)
- Test: `tests/server/test_claims_api.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: `claim_entry(claim, today) -> dict` — island shape + `dbId` + display status mapping (`draft_ready→Draft Ready, failed→Failed, submitted→Submitted, queued→Queued, drafting→Drafting`). `worklist_payload(run, claims, model, today) -> dict` (`generatedOn, asOf, model, totalBilled, claims, summary{processed,drafts,failed}`). `audit_entries(events) -> list[{time,type,detail}]`. `letter_markdown(claim) -> str` (same shape the CLI writes). Routes: `GET /runs/{id}/claims`, `GET /runs/{id}/audit`, `GET /runs/{id}/letters.zip`, `GET /claims/{id}`, `PATCH /claims/{id}`, `GET /claims/{id}/letter.md`.

- [ ] **Step 1: Write the failing tests**

`tests/server/test_claims_api.py`:

```python
import io
import zipfile

from overturn.dryrun import DryRunClient
from server.models import Claim
from server.worker import claim_next_run, process_run
from tests.server.conftest import login
from tests.server.test_runs_api import upload


def drafted_run(client, session_factory):
    login(client)
    run_id = upload(client).json()["runId"]
    with session_factory() as s:
        claim_next_run(s)
    import uuid
    process_run(uuid.UUID(run_id), session_factory=session_factory,
                client=DryRunClient())
    return run_id


def test_worklist_payload_shape(client, session_factory):
    run_id = drafted_run(client, session_factory)
    data = client.get(f"/api/v1/runs/{run_id}/claims").json()
    assert data["summary"] == {"processed": 3, "drafts": 3, "failed": 0}
    assert data["totalBilled"] == 21230.25
    assert data["model"]  # recorded by DbInvocationTracker
    ids = [c["id"] for c in data["claims"]]
    assert ids[0] == "CLM-001"          # overdue first (deadline urgency)
    entry = data["claims"][0]
    for key in ("dbId", "payer", "carc", "carcText", "rarcs", "billed", "dos",
                "denialDate", "deadline", "days", "status", "denialText",
                "letter", "refined", "rule", "error"):
        assert key in entry, key
    assert entry["status"] == "Draft Ready"


def test_audit_endpoint_maps_events(client, session_factory):
    run_id = drafted_run(client, session_factory)
    events = client.get(f"/api/v1/runs/{run_id}/audit").json()
    types = {e["type"] for e in events}
    assert "agent_invocation" in types and "phi_redacted" in types
    assert all(set(e) == {"time", "type", "detail"} for e in events)


def test_patch_letter_edit_and_revert(client, session_factory):
    run_id = drafted_run(client, session_factory)
    entry = client.get(f"/api/v1/runs/{run_id}/claims").json()["claims"][0]
    db_id = entry["dbId"]

    r = client.patch(f"/api/v1/claims/{db_id}", json={"letter": "edited text"})
    assert r.status_code == 200 and r.json()["letter"] == "edited text"

    r = client.patch(f"/api/v1/claims/{db_id}", json={"letter": None})
    assert r.status_code == 200
    assert r.json()["letter"] == entry["letter"]  # restored original


def test_patch_approve_persists(client, session_factory):
    run_id = drafted_run(client, session_factory)
    db_id = client.get(f"/api/v1/runs/{run_id}/claims").json()["claims"][0]["dbId"]
    r = client.patch(f"/api/v1/claims/{db_id}", json={"status": "submitted"})
    assert r.status_code == 200 and r.json()["status"] == "Submitted"
    # persists across a fresh read
    data = client.get(f"/api/v1/runs/{run_id}/claims").json()
    assert data["claims"][0]["status"] == "Submitted"


def test_patch_rules(client, session_factory):
    run_id = drafted_run(client, session_factory)
    db_id = client.get(f"/api/v1/runs/{run_id}/claims").json()["claims"][0]["dbId"]
    assert client.patch(f"/api/v1/claims/{db_id}", json={"status": "won"}).status_code == 422
    with session_factory() as s:
        c = s.query(Claim).filter_by(id=db_id).one()
        c.status = "queued"
        s.commit()
    assert client.patch(f"/api/v1/claims/{db_id}", json={"status": "submitted"}).status_code == 409


def test_letter_and_zip_exports(client, session_factory):
    run_id = drafted_run(client, session_factory)
    db_id = client.get(f"/api/v1/runs/{run_id}/claims").json()["claims"][0]["dbId"]
    md = client.get(f"/api/v1/claims/{db_id}/letter.md")
    assert md.status_code == 200
    assert md.text.startswith("# Appeal — claim CLM-001")
    assert "## Refined recommendation" in md.text

    z = client.get(f"/api/v1/runs/{run_id}/letters.zip")
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert sorted(names) == [
        "CLM-001-appeal.md", "CLM-002-appeal.md", "CLM-003-appeal.md"
    ]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/server/test_claims_api.py -q`
Expected: FAIL — new routes missing.

- [ ] **Step 3: Implement**

Append to `server/payloads.py`:

```python
from datetime import date, datetime

from server.models import AuditEvent, Claim

DISPLAY_STATUS = {
    "queued": "Queued",
    "drafting": "Drafting",
    "draft_ready": "Draft Ready",
    "failed": "Failed",
    "submitted": "Submitted",
}


def claim_entry(claim: Claim, today: date) -> dict:
    days = (claim.appeal_deadline - today).days if claim.appeal_deadline else None
    return {
        "id": claim.claim_id,
        "dbId": str(claim.id),
        "payer": claim.payer,
        "carc": claim.carc_code,
        "carcText": claim.carc_text,
        "rarcs": list(claim.rarc_codes or []),
        "billed": float(claim.billed_amount),
        "dos": claim.service_date.isoformat(),
        "denialDate": claim.denial_date.isoformat(),
        "deadline": claim.appeal_deadline.isoformat() if claim.appeal_deadline else None,
        "days": days,
        "status": DISPLAY_STATUS[claim.status],
        "denialText": claim.denial_reason_text,
        "letter": claim.letter,
        "refined": claim.refined,
        "rule": claim.rule,
        "error": claim.error,
    }


def worklist_payload(
    run: Run, claims: list[Claim], model: str | None, today: date
) -> dict:
    return {
        "generatedOn": run.created_at.date().isoformat(),
        "asOf": today.isoformat(),
        "model": model,
        "totalBilled": float(run.total_billed),
        "claims": [claim_entry(c, today) for c in claims],
        "summary": {
            "processed": run.total_records,
            "drafts": run.drafted,
            "failed": run.failed_records,
        },
    }


def audit_entries(events: list[AuditEvent]) -> list[dict]:
    out = []
    for e in events:
        if e.event_type == "agent_invocation":
            parts = [e.agent, (e.details or {}).get("invocation_type"), e.model, e.error]
            detail = " · ".join(str(p) for p in parts if p)
        else:
            detail = " · ".join(f"{k}={v}" for k, v in (e.details or {}).items()) or e.event_type
        out.append({
            "time": e.ts.strftime("%H:%M:%S"),
            "type": e.event_type,
            "detail": detail[:160],
        })
    return out


def letter_markdown(claim: Claim) -> str:
    body = (
        f"# Appeal — claim {claim.claim_id} ({claim.carc_code}, {claim.payer})\n\n"
        f"{claim.letter or ''}\n"
    )
    if claim.refined:
        body += f"\n---\n\n## Refined recommendation\n\n{claim.refined}\n"
    return body
```

Append to `server/api/runs.py` (worklist ordering matches the worker's urgency order):

```python
import io
import zipfile
from datetime import date

from fastapi import Response
from server.models import AuditEvent
from server.payloads import audit_entries, letter_markdown, worklist_payload


def _ordered_claims(session: Session, run_id: uuid.UUID) -> list[Claim]:
    return list(session.scalars(
        select(Claim)
        .where(Claim.run_id == run_id)
        .order_by(Claim.appeal_deadline.asc().nulls_last(), Claim.billed_amount.desc())
    ))


@router.get("/{run_id}/claims")
def run_claims(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    _user: str = Depends(require_user),
) -> dict:
    run = get_run_or_404(session, run_id)
    model = session.scalars(
        select(AuditEvent.model)
        .where(AuditEvent.run_id == run_id, AuditEvent.model.is_not(None))
        .limit(1)
    ).first()
    return worklist_payload(run, _ordered_claims(session, run_id), model, date.today())


@router.get("/{run_id}/audit")
def run_audit(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    _user: str = Depends(require_user),
) -> list[dict]:
    get_run_or_404(session, run_id)
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.run_id == run_id).order_by(AuditEvent.id)
    ).all()
    return audit_entries(list(events))


@router.get("/{run_id}/letters.zip")
def run_letters_zip(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    _user: str = Depends(require_user),
) -> Response:
    get_run_or_404(session, run_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for claim in _ordered_claims(session, run_id):
            if claim.letter:
                z.writestr(f"{claim.claim_id}-appeal.md", letter_markdown(claim))
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="letters.zip"'},
    )
```

`server/api/claims.py`:

```python
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.api.deps import get_session
from server.models import Claim, utcnow
from server.payloads import claim_entry, letter_markdown
from server.security import require_user

router = APIRouter(prefix="/claims", tags=["claims"])


class ClaimPatch(BaseModel):
    letter: str | None = None
    status: str | None = None


def get_claim_or_404(session: Session, claim_id: uuid.UUID) -> Claim:
    claim = session.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return claim


@router.get("/{claim_id}")
def get_claim(
    claim_id: uuid.UUID,
    session: Session = Depends(get_session),
    _user: str = Depends(require_user),
) -> dict:
    return claim_entry(get_claim_or_404(session, claim_id), date.today())


@router.patch("/{claim_id}")
def patch_claim(
    claim_id: uuid.UUID,
    patch: ClaimPatch,
    session: Session = Depends(get_session),
    _user: str = Depends(require_user),
) -> dict:
    claim = get_claim_or_404(session, claim_id)
    if claim.run.is_demo:
        raise HTTPException(409, detail="demo run is read-only")
    if claim.status not in ("draft_ready", "submitted"):
        raise HTTPException(409, detail=f"claim is {claim.status}; not editable yet")

    if patch.status is not None:
        if patch.status != "submitted":
            raise HTTPException(422, detail="status may only be set to 'submitted'")
        claim.status = "submitted"
    if "letter" in patch.model_fields_set:
        claim.letter = claim.letter_original if patch.letter is None else patch.letter
    claim.updated_at = utcnow()
    return claim_entry(claim, date.today())


@router.get("/{claim_id}/letter.md")
def claim_letter(
    claim_id: uuid.UUID,
    session: Session = Depends(get_session),
    _user: str = Depends(require_user),
) -> Response:
    claim = get_claim_or_404(session, claim_id)
    if not claim.letter:
        raise HTTPException(404, detail="no letter drafted for this claim")
    return Response(
        letter_markdown(claim),
        media_type="text/markdown",
        headers={
            "Content-Disposition":
                f'attachment; filename="{claim.claim_id}-appeal.md"'
        },
    )
```

In `server/app.py` include it: `from server.api import auth, claims, runs` and `api.include_router(claims.router)`.

- [ ] **Step 4: Run to verify pass; commit**

Run: `.venv/bin/python -m pytest tests/server/ -q` — all pass.

```bash
git add server/ tests/server/test_claims_api.py
git commit -m "server: claims API, worklist/audit payloads, letter exports, persistent PATCH"
```

---

### Task 7: Demo run — seeding and public read-only endpoints

**Files:**
- Create: `server/demo.py`
- Create: `server/api/demo.py`
- Modify: `server/app.py` (include demo router; seed on lifespan when `demo_mode`)
- Test: `tests/server/test_demo.py`

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: `server.demo.seed_demo(session_factory) -> uuid.UUID` (idempotent: returns existing demo run id if present; otherwise creates a 50-record synthetic run, drafts it inline with `DryRunClient`, marks `is_demo=True`). Routes (no auth): `GET /api/v1/demo/claims`, `GET /api/v1/demo/audit`.

- [ ] **Step 1: Write the failing tests**

`tests/server/test_demo.py`:

```python
from server.demo import seed_demo
from server.models import Run


def test_seed_demo_is_idempotent(session_factory):
    a = seed_demo(session_factory)
    b = seed_demo(session_factory)
    assert a == b
    with session_factory() as s:
        run = s.query(Run).one()
        assert run.is_demo and run.dry_run
        assert run.status == "completed"
        assert run.total_records == 50 and run.drafted == 50


def test_demo_endpoints_are_public_and_read_only(client, session_factory):
    seed_demo(session_factory)
    data = client.get("/api/v1/demo/claims").json()      # no login
    assert data["summary"]["processed"] == 50
    assert len(data["claims"]) == 50
    audit = client.get("/api/v1/demo/audit").json()
    assert len(audit) > 0

    # write endpoints refuse the demo run even when authenticated
    from tests.server.conftest import login
    login(client)
    db_id = data["claims"][0]["dbId"]
    assert client.patch(
        f"/api/v1/claims/{db_id}", json={"status": "submitted"}
    ).status_code == 409


def test_demo_404_when_not_seeded(client):
    assert client.get("/api/v1/demo/claims").status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/server/test_demo.py -q`
Expected: FAIL — `server.demo` missing.

- [ ] **Step 3: Implement**

`server/demo.py`:

```python
"""Seed the public read-only demo run: 50 synthetic denials, dry-run drafted.

Synthetic data only — every name, claim id, and dollar figure is invented by
the package's seeded generator.
"""
import uuid
from datetime import date
from typing import Callable

from healthflow_agents.tools.remittance_parser import make_synthetic_denials
from sqlalchemy import select

from overturn.dryrun import DryRunClient
from server.models import Claim, Run
from server.worker import process_run

DEMO_SEED = 2026
DEMO_SIZE = 50


def seed_demo(session_factory: Callable) -> uuid.UUID:
    with session_factory() as session:
        existing = session.scalars(
            select(Run).where(Run.is_demo.is_(True)).limit(1)
        ).first()
        if existing is not None:
            return existing.id

        records = make_synthetic_denials(
            DEMO_SIZE, seed=DEMO_SEED, base_date=date.today()
        )
        run = Run(
            filename="demo-synthetic.csv", dry_run=True, is_demo=True,
            status="running", total_records=len(records),
            total_billed=round(sum(r.billed_amount for r in records), 2),
        )
        session.add(run)
        session.flush()
        for r in records:
            session.add(Claim(
                run_id=run.id, claim_id=r.claim_id, payer=r.payer,
                carc_code=r.carc_code, rarc_codes=list(r.rarc_codes),
                billed_amount=r.billed_amount, service_date=r.service_date,
                denial_date=r.denial_date, appeal_deadline=r.appeal_deadline,
                denial_reason_text=r.denial_reason_text,
            ))
        session.commit()
        run_id = run.id

    process_run(run_id, session_factory=session_factory, client=DryRunClient())
    return run_id
```

`server/api/demo.py`:

```python
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.api.deps import get_session
from server.api.runs import _ordered_claims
from server.models import AuditEvent, Run
from server.payloads import audit_entries, worklist_payload

router = APIRouter(prefix="/demo", tags=["demo"])


def _demo_run(session: Session) -> Run:
    run = session.scalars(select(Run).where(Run.is_demo.is_(True)).limit(1)).first()
    if run is None:
        raise HTTPException(status_code=404, detail="demo run not seeded")
    return run


@router.get("/claims")
def demo_claims(session: Session = Depends(get_session)) -> dict:
    run = _demo_run(session)
    return worklist_payload(run, _ordered_claims(session, run.id), None, date.today())


@router.get("/audit")
def demo_audit(session: Session = Depends(get_session)) -> list[dict]:
    run = _demo_run(session)
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.run_id == run.id).order_by(AuditEvent.id)
    ).all()
    return audit_entries(list(events))
```

In `server/app.py`: include `demo.router` in the api router, and seed on startup via lifespan:

```python
from contextlib import asynccontextmanager

def create_app(settings: Settings, session_factory) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if settings.demo_mode:
            from server.demo import seed_demo
            seed_demo(session_factory)
        yield

    app = FastAPI(title="Overturn", version="0.1.0", lifespan=lifespan)
    ...
```

(The `client` test fixture uses `demo_mode=False`, so seeding stays explicit
in tests.)

- [ ] **Step 4: Run to verify pass; commit**

Run: `.venv/bin/python -m pytest tests/server/ -q` — all pass. Run `.venv/bin/python -m pytest tests/ -q` — CLI suite still green.

```bash
git add server/ tests/server/test_demo.py
git commit -m "server: public read-only demo run, seeded at startup"
```

---

### Task 8: Frontend — API client, mutations layer, workbench API mode

**Files:**
- Create: `frontend/src/app/api.ts`
- Modify: `frontend/src/types.ts` (add `dbId?: string` to `Claim`)
- Modify: `frontend/src/App.tsx` (optional `mutations` prop; API-aware handlers)
- Test: `frontend/src/__tests__/api.test.ts`
- Test: `frontend/src/__tests__/workbench-mutations.test.tsx`

**Interfaces:**
- Consumes: existing workbench (`App`, `types.ts`, `lib/worklist.ts`).
- Produces:
  - `api.ts`: `ApiError` (has `status: number`); `login(email, password)`, `logout()`, `me()` (`{email} | null` — null on 401); `uploadRun(file: File, dryRun: boolean) -> {runId}`; `listRuns() -> RunInfo[]`; `getRun(id) -> RunInfo`; `getRunClaims(id) -> WorkbenchData & {claims: Claim[]}`; `getRunAudit(id) -> AuditEvent[]`; `getDemoClaims()`, `getDemoAudit()`; `patchClaim(dbId, body) -> Claim`; `retryRun(id)`. `RunInfo` type: `{id, filename, dryRun, isDemo, status, totalRecords, drafted, failedRecords, totalBilled, error, createdAt, startedAt, finishedAt}`.
  - `App` accepts `mutations?: WorkbenchMutations` where `interface WorkbenchMutations { approve(c: Claim): Promise<void>; saveLetter(c: Claim, text: string): Promise<void>; revertLetter(c: Claim): Promise<string> }` (exported from `App.tsx`). With `mutations` present: Approve awaits `approve` then applies the local override with toast "approved — saved"; letter edits update local state immediately and debounce `saveLetter` 800 ms; Revert awaits `revertLetter` and sets the local letter to the returned string. Without `mutations`, behavior is unchanged (island mode).

- [ ] **Step 1: Write the failing tests**

`frontend/src/__tests__/api.test.ts`:

```ts
import { afterEach, expect, test, vi } from 'vitest';
import { ApiError, getRunClaims, me, patchClaim, uploadRun } from '../app/api';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);
afterEach(() => fetchMock.mockReset());

const ok = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

test('me returns null on 401 instead of throwing', async () => {
  fetchMock.mockReturnValueOnce(ok({ detail: 'nope' }, 401));
  expect(await me()).toBeNull();
});

test('uploadRun posts multipart with dry_run field', async () => {
  fetchMock.mockReturnValueOnce(ok({ runId: 'r1' }, 202));
  const file = new File(['csv'], 'denials.csv', { type: 'text/csv' });
  const out = await uploadRun(file, true);
  expect(out.runId).toBe('r1');
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe('/api/v1/runs');
  expect(init.method).toBe('POST');
  expect(init.body).toBeInstanceOf(FormData);
  expect((init.body as FormData).get('dry_run')).toBe('true');
});

test('errors carry status and server detail', async () => {
  fetchMock.mockReturnValueOnce(ok({ detail: 'cap exceeded' }, 413));
  await expect(uploadRun(new File([''], 'x.csv'), true)).rejects.toMatchObject({
    status: 413,
    message: 'cap exceeded',
  });
  fetchMock.mockReturnValueOnce(ok({ detail: 'x' }, 413));
  await expect(uploadRun(new File([''], 'x.csv'), true)).rejects.toBeInstanceOf(ApiError);
});

test('patchClaim PATCHes json body', async () => {
  fetchMock.mockReturnValueOnce(ok({ id: 'CLM-1', status: 'Submitted' }));
  await patchClaim('db-1', { status: 'submitted' });
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe('/api/v1/claims/db-1');
  expect(init.method).toBe('PATCH');
  expect(JSON.parse(init.body as string)).toEqual({ status: 'submitted' });
});

test('getRunClaims hits the worklist endpoint', async () => {
  fetchMock.mockReturnValueOnce(ok({ claims: [] }));
  await getRunClaims('r1');
  expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/runs/r1/claims');
});
```

`frontend/src/__tests__/workbench-mutations.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import App, { type WorkbenchMutations } from '../App';
import { SAMPLE_DATA } from '../fixtures/sample';

function mutations(over: Partial<WorkbenchMutations> = {}): WorkbenchMutations {
  return {
    approve: vi.fn().mockResolvedValue(undefined),
    saveLetter: vi.fn().mockResolvedValue(undefined),
    revertLetter: vi.fn().mockResolvedValue('ORIGINAL FROM SERVER'),
    ...over,
  };
}

test('approve awaits server then marks Submitted', async () => {
  const m = mutations();
  render(<App data={SAMPLE_DATA} mutations={m} />);
  await userEvent.click(screen.getByText('CLM-0001'));
  await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
  expect(m.approve).toHaveBeenCalledOnce();
  expect(await screen.findByText('Submitted')).toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('saved');
});

test('letter edits debounce a saveLetter call', async () => {
  vi.useFakeTimers();
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  const m = mutations();
  render(<App data={SAMPLE_DATA} mutations={m} />);
  await user.click(screen.getByText('CLM-0001'));
  await user.type(screen.getByRole('textbox'), 'X');
  expect(m.saveLetter).not.toHaveBeenCalled();
  vi.advanceTimersByTime(900);
  expect(m.saveLetter).toHaveBeenCalledOnce();
  vi.useRealTimers();
});

test('revert uses server-restored letter', async () => {
  const m = mutations();
  render(<App data={SAMPLE_DATA} mutations={m} />);
  await userEvent.click(screen.getByText('CLM-0001'));
  await userEvent.click(screen.getByRole('button', { name: 'Revert draft' }));
  expect(m.revertLetter).toHaveBeenCalledOnce();
  expect(
    await screen.findByDisplayValue('ORIGINAL FROM SERVER'),
  ).toBeInTheDocument();
});

test('approve failure shows error toast and keeps status', async () => {
  const m = mutations({ approve: vi.fn().mockRejectedValue(new Error('offline')) });
  render(<App data={SAMPLE_DATA} mutations={m} />);
  await userEvent.click(screen.getByText('CLM-0001'));
  await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
  expect(await screen.findByRole('status')).toHaveTextContent('offline');
  expect(screen.queryByText('Submitted')).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/__tests__/api.test.ts src/__tests__/workbench-mutations.test.tsx`
Expected: FAIL — `../app/api` missing; App has no `mutations` prop.

- [ ] **Step 3: Implement**

`frontend/src/app/api.ts`:

```ts
import type { AuditEvent, Claim, WorkbenchData } from '../types';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export interface RunInfo {
  id: string;
  filename: string;
  dryRun: boolean;
  isDemo: boolean;
  status: 'queued' | 'running' | 'completed' | 'failed';
  totalRecords: number;
  drafted: number;
  failedRecords: number;
  totalBilled: number;
  error: string | null;
  createdAt: string | null;
  startedAt: string | null;
  finishedAt: string | null;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { credentials: 'same-origin', ...init });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch { /* non-json error body */ }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export const login = (email: string, password: string) =>
  request<{ email: string }>('/api/v1/auth/login', json('POST', { email, password }));

export const logout = () => request<{ ok: boolean }>('/api/v1/auth/logout', { method: 'POST' });

export async function me(): Promise<{ email: string } | null> {
  try {
    return await request<{ email: string }>('/api/v1/auth/me');
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null;
    throw e;
  }
}

export function uploadRun(file: File, dryRun: boolean): Promise<{ runId: string }> {
  const body = new FormData();
  body.append('file', file);
  body.append('dry_run', String(dryRun));
  return request('/api/v1/runs', { method: 'POST', body });
}

export const listRuns = () => request<RunInfo[]>('/api/v1/runs');
export const getRun = (id: string) => request<RunInfo>(`/api/v1/runs/${id}`);
export const retryRun = (id: string) =>
  request<{ requeued: number }>(`/api/v1/runs/${id}/retry`, { method: 'POST' });
export const getRunClaims = (id: string) =>
  request<WorkbenchData>(`/api/v1/runs/${id}/claims`);
export const getRunAudit = (id: string) =>
  request<AuditEvent[]>(`/api/v1/runs/${id}/audit`);
export const getDemoClaims = () => request<WorkbenchData>('/api/v1/demo/claims');
export const getDemoAudit = () => request<AuditEvent[]>('/api/v1/demo/audit');
export const patchClaim = (
  dbId: string,
  body: { letter?: string | null; status?: 'submitted' },
) => request<Claim>(`/api/v1/claims/${dbId}`, json('PATCH', body));
```

In `frontend/src/types.ts`, add to `Claim`:

```ts
  /** Server row id for mutations; absent in static-report (island) mode. */
  dbId?: string;
```

In `frontend/src/App.tsx`:
- Export the mutations contract and accept it as a prop:

```tsx
export interface WorkbenchMutations {
  approve(c: Claim): Promise<void>;
  saveLetter(c: Claim, text: string): Promise<void>;
  revertLetter(c: Claim): Promise<string>;
}

export default function App({
  data,
  mutations,
}: { data: WorkbenchData; mutations?: WorkbenchMutations }) {
```

- Add a debounce ref next to the toast timer:

```tsx
  const saveTimer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(saveTimer.current), []);
```

- Replace the three detail handlers:

```tsx
          onLetterChange={(text) => {
            setLetters((l) => ({ ...l, [claim.id]: text }));
            if (mutations) {
              clearTimeout(saveTimer.current);
              saveTimer.current = setTimeout(() => {
                mutations.saveLetter(claim, text).catch((e) => showToast(String(e.message ?? e)));
              }, 800);
            }
          }}
          onApprove={() => {
            const apply = () => {
              setStatusOverrides((o) => ({ ...o, [claim.id]: 'Submitted' }));
              showToast(
                mutations
                  ? `${claim.id} approved — saved`
                  : `${claim.id} approved — marked Submitted (this session only)`,
              );
            };
            if (mutations) {
              mutations.approve(claim).then(apply).catch((e) => showToast(String(e.message ?? e)));
            } else {
              apply();
            }
          }}
          onRevert={() => {
            const applyLocal = (restored?: string) => {
              setLetters((l) => {
                const next = { ...l };
                if (restored !== undefined) next[claim.id] = restored;
                else delete next[claim.id];
                return next;
              });
              showToast('Draft reverted to the generated letter');
            };
            if (mutations) {
              mutations.revertLetter(claim).then(applyLocal).catch((e) => showToast(String(e.message ?? e)));
            } else {
              applyLocal();
            }
          }}
```

(Export/`downloadLetter` stays purely client-side in both modes — no change.)

- [ ] **Step 4: Run to verify pass; commit**

Run: `cd frontend && npm test && npm run build` — all tests pass (36 prior + 9 new), tsc clean. Also `npm run build:template` still succeeds (island mode untouched).

```bash
git add frontend/src
git commit -m "frontend: API client and workbench mutations layer (persistent approve/edit/revert)"
```

---

### Task 9: Frontend — SPA entry: login, runs, hash routing, second build target

**Files:**
- Create: `frontend/app.html`
- Create: `frontend/vite.app.config.ts`
- Create: `frontend/scripts/finalize-app.mjs`
- Create: `frontend/src/app/main.tsx`
- Create: `frontend/src/app/ServerApp.tsx`
- Create: `frontend/src/app/LoginScreen.tsx`
- Create: `frontend/src/app/RunsScreen.tsx`
- Modify: `frontend/package.json` (scripts `dev:app`, `build:app`)
- Test: `frontend/src/__tests__/server-app.test.tsx`

**Interfaces:**
- Consumes: Task 8 `api.ts` + workbench `App` with `mutations`.
- Produces: SPA at `dist-app/` (index.html + assets) with: unauthenticated → demo workbench (read-only, banner + Sign in) or Login screen; authenticated → Runs screen (upload with dry-run toggle, 2 s polling while any run is queued/running, progress bars, retry button on failed runs) and `#/runs/<id>` → workbench with mutations. npm scripts: `dev:app` (Vite dev server proxying `/api` → `http://localhost:8000`), `build:app`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/__tests__/server-app.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { ServerApp } from '../app/ServerApp';
import { SAMPLE_DATA } from '../fixtures/sample';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);

const ok = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

const RUN = {
  id: 'r1', filename: 'denials.csv', dryRun: true, isDemo: false,
  status: 'completed', totalRecords: 3, drafted: 3, failedRecords: 0,
  totalBilled: 21230.25, error: null,
  createdAt: '2026-07-08T00:00:00Z', startedAt: null, finishedAt: null,
};

beforeEach(() => { window.location.hash = ''; });
afterEach(() => fetchMock.mockReset());

test('logged out: demo workbench with sign-in affordance', async () => {
  fetchMock.mockImplementation((url: string) => {
    if (url === '/api/v1/auth/me') return ok({ detail: 'x' }, 401);
    if (url === '/api/v1/demo/claims') return ok(SAMPLE_DATA);
    return ok({}, 404);
  });
  render(<ServerApp />);
  expect(await screen.findByText(/synthetic/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  expect(await screen.findByText('CLM-0001')).toBeInTheDocument();
});

test('login flow reaches the runs screen', async () => {
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (url === '/api/v1/auth/me') return ok({ detail: 'x' }, 401);
    if (url === '/api/v1/auth/login') return ok({ email: 'a@b.c' });
    if (url === '/api/v1/runs' && (!init || !init.method)) return ok([RUN]);
    if (url === '/api/v1/demo/claims') return ok(SAMPLE_DATA);
    return ok({}, 404);
  });
  render(<ServerApp />);
  await userEvent.click(await screen.findByRole('button', { name: /sign in/i }));
  await userEvent.type(screen.getByLabelText(/email/i), 'a@b.c');
  await userEvent.type(screen.getByLabelText(/password/i), 'pw');
  await userEvent.click(screen.getByRole('button', { name: /log in/i }));
  expect(await screen.findByText('denials.csv')).toBeInTheDocument();
  expect(screen.getByText(/3 \/ 3 drafted/)).toBeInTheDocument();
});

test('opening a run loads the workbench via hash route', async () => {
  window.location.hash = '#/runs/r1';
  fetchMock.mockImplementation((url: string) => {
    if (url === '/api/v1/auth/me') return ok({ email: 'a@b.c' });
    if (url === '/api/v1/runs/r1') return ok(RUN);
    if (url === '/api/v1/runs/r1/claims') return ok(SAMPLE_DATA);
    return ok({}, 404);
  });
  render(<ServerApp />);
  expect(await screen.findByText('CLM-0001')).toBeInTheDocument();
  await waitFor(() =>
    expect(fetchMock.mock.calls.map((c) => c[0])).toContain('/api/v1/runs/r1/claims'),
  );
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/__tests__/server-app.test.tsx`
Expected: FAIL — `../app/ServerApp` missing.

- [ ] **Step 3: Implement**

`frontend/app.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Overturn</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400..700&family=Spline+Sans+Mono:wght@400..700&display=swap" rel="stylesheet">
</head>
<body>
<div id="app"></div>
<script type="module" src="/src/app/main.tsx"></script>
</body>
</html>
```

`frontend/vite.app.config.ts`:

```ts
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist-app',
    rollupOptions: { input: 'app.html' },
  },
  server: {
    proxy: { '/api': 'http://localhost:8000' },
  },
});
```

`frontend/scripts/finalize-app.mjs`:

```js
import { renameSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const dist = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist-app');
const from = join(dist, 'app.html');
const to = join(dist, 'index.html');
if (!existsSync(from)) {
  console.error('FATAL: dist-app/app.html not found — did the build run?');
  process.exit(1);
}
renameSync(from, to);
console.log(`renamed app.html -> index.html in ${dist}`);
```

In `frontend/package.json` scripts add:

```json
    "dev:app": "vite --config vite.app.config.ts",
    "build:app": "tsc --noEmit && vite build --config vite.app.config.ts && node scripts/finalize-app.mjs",
```

`frontend/src/app/main.tsx`:

```tsx
import React from 'react';
import { createRoot } from 'react-dom/client';
import '../styles.css';
import { ServerApp } from './ServerApp';

createRoot(document.getElementById('app')!).render(
  <React.StrictMode>
    <ServerApp />
  </React.StrictMode>,
);
```

`frontend/src/app/LoginScreen.tsx`:

```tsx
import { useState } from 'react';
import { login } from './api';

export function LoginScreen({ onLoggedIn }: { onLoggedIn: (email: string) => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const user = await login(email, password);
      onLoggedIn(user.email);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="detail" style={{ maxWidth: 420, margin: '48px auto' }}>
      <div className="card" style={{ padding: '24px 28px' }}>
        <div className="card-title" style={{ fontSize: 17, marginBottom: 14 }}>
          Sign in to Overturn
        </div>
        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <label style={{ fontSize: 12.5, color: 'var(--mut)' }}>
            Email
            <input
              type="email" value={email} required
              onChange={(e) => setEmail(e.target.value)}
              style={{ display: 'block', width: '100%', marginTop: 4, padding: '7px 10px',
                       border: '1px solid #DBD8D1', borderRadius: 8, font: 'inherit' }}
            />
          </label>
          <label style={{ fontSize: 12.5, color: 'var(--mut)' }}>
            Password
            <input
              type="password" value={password} required
              onChange={(e) => setPassword(e.target.value)}
              style={{ display: 'block', width: '100%', marginTop: 4, padding: '7px 10px',
                       border: '1px solid #DBD8D1', borderRadius: 8, font: 'inherit' }}
            />
          </label>
          {error && <div style={{ fontSize: 12.5, color: 'var(--red-fg)' }}>{error}</div>}
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? 'Signing in…' : 'Log in'}
          </button>
        </form>
      </div>
    </div>
  );
}
```

`frontend/src/app/RunsScreen.tsx`:

```tsx
import { useCallback, useEffect, useRef, useState } from 'react';
import { fmtMoney } from '../lib/format';
import { listRuns, retryRun, uploadRun, type RunInfo } from './api';

const ACTIVE = new Set(['queued', 'running']);

export function RunsScreen({ onOpenRun }: { onOpenRun: (id: string) => void }) {
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [dryRun, setDryRun] = useState(true);
  const [error, setError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      setRuns(await listRuns());
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!runs.some((r) => ACTIVE.has(r.status))) return;
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [runs, refresh]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setError('');
    try {
      await uploadRun(file, dryRun);
      if (fileRef.current) fileRef.current.value = '';
      await refresh();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  };

  return (
    <div className="sm"><div className="sm-inner">
      <div className="sm-head">
        <div className="sm-title">Runs</div>
        <div className="sm-meta">synthetic data only — demonstration system, not production RCM software</div>
      </div>
      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">New batch</div>
        <form onSubmit={submit}
              style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12, flexWrap: 'wrap' }}>
          <input ref={fileRef} type="file" accept=".csv,.json" required style={{ font: 'inherit', fontSize: 13 }} />
          <label style={{ fontSize: 12.5, color: 'var(--ink-2)', display: 'flex', gap: 6, alignItems: 'center' }}>
            <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
            Dry run (no Claude refinement, no API cost)
          </label>
          <button type="submit" className="btn-primary">Upload &amp; draft appeals</button>
        </form>
        <div className="sm-note" style={{ marginTop: 10 }}>
          Simplified-835 CSV or JSON. Do not upload real PHI — this deployment is not BAA-covered.
        </div>
        {error && <div style={{ fontSize: 12.5, color: 'var(--red-fg)', marginTop: 8 }}>{error}</div>}
      </div>
      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-title">Batches</div>
        <div style={{ display: 'flex', flexDirection: 'column', marginTop: 8 }}>
          {runs.length === 0 && <div className="sm-note">No runs yet — upload a remittance above.</div>}
          {runs.map((r) => {
            const done = r.drafted + r.failedRecords;
            const pct = r.totalRecords ? Math.round((done / r.totalRecords) * 100) : 0;
            return (
              <div key={r.id} className="audit-row" style={{ cursor: 'pointer', gap: 14 }}
                   onClick={() => onOpenRun(r.id)}>
                <div style={{ flex: 'none', fontFamily: 'var(--mono)', fontSize: 12 }}>{r.filename}</div>
                <span className={`pill ${r.status === 'failed' ? 'c-red' : r.status === 'completed' ? 'c-green' : 'c-amber'}`}>
                  {r.status}
                </span>
                <div className="bar-track" style={{ flex: 1, maxWidth: 220 }}>
                  <div className="bar-fill" style={{ width: `${pct}%` }} />
                </div>
                <div style={{ fontFamily: 'var(--mono)', fontSize: 11.5, color: 'var(--mut)' }}>
                  {done} / {r.totalRecords} drafted · {fmtMoney(r.totalBilled)}
                </div>
                {r.status === 'failed' && (
                  <button type="button" className="btn"
                          onClick={(e) => { e.stopPropagation(); retryRun(r.id).then(refresh); }}>
                    Retry
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div></div>
  );
}
```

`frontend/src/app/ServerApp.tsx`:

```tsx
import { useCallback, useEffect, useState } from 'react';
import App, { type WorkbenchMutations } from '../App';
import type { WorkbenchData } from '../types';
import {
  getDemoClaims, getRun, getRunClaims, logout, me, patchClaim,
} from './api';
import { LoginScreen } from './LoginScreen';
import { RunsScreen } from './RunsScreen';

type Route = { name: 'runs' } | { name: 'run'; id: string };

function parseHash(): Route {
  const m = window.location.hash.match(/^#\/runs\/(.+)$/);
  return m ? { name: 'run', id: m[1] } : { name: 'runs' };
}

function makeMutations(): WorkbenchMutations {
  return {
    async approve(c) {
      if (!c.dbId) throw new Error('read-only view');
      await patchClaim(c.dbId, { status: 'submitted' });
    },
    async saveLetter(c, text) {
      if (!c.dbId) throw new Error('read-only view');
      await patchClaim(c.dbId, { letter: text });
    },
    async revertLetter(c) {
      if (!c.dbId) throw new Error('read-only view');
      const updated = await patchClaim(c.dbId, { letter: null });
      return updated.letter ?? '';
    },
  };
}

export function ServerApp() {
  const [user, setUser] = useState<string | null | undefined>(undefined);
  const [route, setRoute] = useState<Route>(parseHash());
  const [showLogin, setShowLogin] = useState(false);
  const [demo, setDemo] = useState<WorkbenchData | null>(null);
  const [worklist, setWorklist] = useState<WorkbenchData | null>(null);
  const [runActive, setRunActive] = useState(false);

  useEffect(() => {
    me().then((u) => setUser(u?.email ?? null));
    const onHash = () => setRoute(parseHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    if (user === null) getDemoClaims().then(setDemo).catch(() => setDemo(null));
  }, [user]);

  const loadRun = useCallback(async (id: string) => {
    const [info, data] = await Promise.all([getRun(id), getRunClaims(id)]);
    setWorklist(data);
    setRunActive(info.status === 'queued' || info.status === 'running');
  }, []);

  useEffect(() => {
    if (user && route.name === 'run') {
      setWorklist(null);
      loadRun(route.id);
    }
  }, [user, route, loadRun]);

  useEffect(() => {
    if (!runActive || route.name !== 'run') return;
    const t = setInterval(() => loadRun(route.id), 2000);
    return () => clearInterval(t);
  }, [runActive, route, loadRun]);

  if (user === undefined) return null;

  if (!user) {
    if (showLogin) {
      return <LoginScreen onLoggedIn={(email) => { setUser(email); setShowLogin(false); }} />;
    }
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 20px',
                      background: 'var(--amber-bg)', color: 'var(--amber-fg)', fontSize: 12.5, fontWeight: 600 }}>
          Read-only demo — synthetic data only.
          <div className="spacer" />
          <button type="button" className="btn" onClick={() => setShowLogin(true)}>Sign in</button>
        </div>
        {demo ? <App data={demo} /> : <div className="sm-note" style={{ padding: 24 }}>Loading demo…</div>}
      </div>
    );
  }

  if (route.name === 'run') {
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 20px',
                      borderBottom: '1px solid var(--line)', fontSize: 12.5 }}>
          <button type="button" className="backlink" onClick={() => { window.location.hash = ''; }}>
            ← Runs
          </button>
          {runActive && <span className="pill c-amber">drafting in progress — refreshing</span>}
          <div className="spacer" />
          <button type="button" className="btn" onClick={() => logout().then(() => setUser(null))}>
            Log out
          </button>
        </div>
        {worklist
          ? <App data={worklist} mutations={makeMutations()} />
          : <div className="sm-note" style={{ padding: 24 }}>Loading worklist…</div>}
      </div>
    );
  }

  return <RunsScreen onOpenRun={(id) => { window.location.hash = `#/runs/${id}`; }} />;
}
```

- [ ] **Step 4: Run to verify pass; commit**

Run: `cd frontend && npm test && npm run build:app && npm run build:template`
Expected: all vitest suites pass; `dist-app/index.html` exists; template build unchanged.

```bash
git add frontend
git commit -m "frontend: SPA entry — login, runs screen with polling, hash-routed workbench"
```

---

### Task 10: Docker, compose services, Railway deploy docs

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Modify: `docker-compose.yml` (add web + worker services)
- Modify: `README.md` (Server & Deployment section)

**Interfaces:**
- Consumes: everything prior.
- Produces: `docker compose up` runs db + web (`:8000`) + worker locally; README documents Railway (two services, one image, env vars).

- [ ] **Step 1: Write Dockerfile and .dockerignore**

`Dockerfile`:

```dockerfile
# ---- frontend build ----
FROM node:20-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build:app

# ---- python runtime ----
FROM python:3.13-slim
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY overturn ./overturn
RUN pip install --no-cache-dir ".[server]"
COPY server ./server
COPY alembic.ini ./
COPY --from=frontend /build/dist-app ./frontend/dist-app
ENV SPA_DIR=/app/frontend/dist-app
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn server.app:app --host 0.0.0.0 --port 8000"]
```

`.dockerignore`:

```
.venv
.git
frontend/node_modules
frontend/dist
frontend/dist-app
tests
docs
.superpowers
.pytest_cache
__pycache__
results
```

- [ ] **Step 2: Extend docker-compose.yml**

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: overturn
      POSTGRES_PASSWORD: overturn
      POSTGRES_DB: overturn
    ports:
      - "5433:5432"
    volumes:
      - db-data:/var/lib/postgresql/data
      - ./docker/db-init.sql:/docker-entrypoint-initdb.d/db-init.sql
  web:
    build: .
    ports:
      - "8000:8000"
    environment: &appenv
      DATABASE_URL: postgresql+psycopg://overturn:overturn@db:5432/overturn
      ADMIN_EMAIL: admin@example.com
      ADMIN_PASSWORD: change-me-locally
      SECRET_KEY: dev-secret-not-for-prod
      DEMO_MODE: "1"
      # ANTHROPIC_API_KEY: set in your shell to enable live runs
    depends_on:
      - db
  worker:
    build: .
    command: python -m server.worker
    environment: *appenv
    depends_on:
      - db
volumes:
  db-data:
```

- [ ] **Step 3: Build and smoke-test locally**

Run: `docker compose build && docker compose up -d && sleep 8 && curl -s http://localhost:8000/api/v1/demo/claims | head -c 200 && curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/`
Expected: demo claims JSON prefix; `200` for the SPA index. Then `docker compose logs worker --tail 5` shows the polling message. Leave the stack running for Task 11.

- [ ] **Step 4: README section**

Append after the Frontend subsection in `README.md`:

```markdown
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
  .venv/bin/uvicorn server.app:app --reload &
DATABASE_URL=... .venv/bin/python -m server.worker &
cd frontend && npm run dev:app   # Vite dev server proxying /api
```

Deploy (Railway): create a project with a Postgres plugin and two services
from this repo's Dockerfile — **web** (default CMD) and **worker**
(override start command to `python -m server.worker`). Set on both:
`DATABASE_URL` (from the plugin), `ADMIN_EMAIL`, `ADMIN_PASSWORD`,
`SECRET_KEY`, `ANTHROPIC_API_KEY` (optional — dry runs work without it),
`MAX_UPLOAD_RECORDS` (default 200), `DEMO_MODE` (default 1). Migrations run
automatically when the web service starts.
```

- [ ] **Step 5: Run the full test suites; commit**

Run: `.venv/bin/python -m pytest tests/ -q && cd frontend && npm test`
Expected: all green.

```bash
git add Dockerfile .dockerignore docker-compose.yml README.md
git commit -m "server: Dockerfile, compose stack (db/web/worker), Railway deploy docs"
```

---

### Task 11: E2E — login → upload → poll → approve → persist

**Files:**
- Create: `frontend/e2e/server.spec.ts`
- Create: `frontend/playwright.config.ts`
- Modify: `frontend/package.json` (devDependency `@playwright/test`, script `e2e`)

**Interfaces:**
- Consumes: the running compose stack from Task 10 (`http://localhost:8000`).
- Produces: `npm run e2e` — one spec proving the persistence loop end-to-end with a dry-run batch.

- [ ] **Step 1: Add Playwright**

Run: `cd frontend && npm install -D @playwright/test && npx playwright install chromium`

`frontend/playwright.config.ts`:

```ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'e2e',
  use: { baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8000' },
  timeout: 120_000,
});
```

Add to `frontend/package.json` scripts: `"e2e": "playwright test"`.

- [ ] **Step 2: Write the spec**

`frontend/e2e/server.spec.ts`:

```ts
import { expect, test } from '@playwright/test';

const CSV = `claim_id,payer,carc_code,rarc_codes,denial_reason_text,billed_amount,service_date,denial_date,appeal_deadline
CLM-E2E-1,Synthetic Payer A,CO-50,N115,These are non-covered services because this is not deemed a medical necessity.,12500.00,2026-04-10,2026-05-01,2026-08-30
CLM-E2E-2,Synthetic Payer B,CO-29,N30,The time limit for filing has expired.,430.25,2026-03-02,2026-04-15,2026-09-15
`;

test('upload → draft → approve → persists across reload', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.getByLabel(/email/i).fill(process.env.E2E_EMAIL ?? 'admin@example.com');
  await page.getByLabel(/password/i).fill(process.env.E2E_PASSWORD ?? 'change-me-locally');
  await page.getByRole('button', { name: /log in/i }).click();

  await page.setInputFiles('input[type=file]', {
    name: 'e2e-denials.csv', mimeType: 'text/csv', buffer: Buffer.from(CSV),
  });
  await page.getByRole('button', { name: /upload/i }).click();

  const row = page.locator('.audit-row', { hasText: 'e2e-denials.csv' }).first();
  await expect(row.getByText('completed')).toBeVisible({ timeout: 90_000 });

  await row.click();
  await expect(page.getByText('CLM-E2E-1')).toBeVisible();
  await page.getByText('CLM-E2E-1').click();
  await page.getByRole('button', { name: 'Approve' }).click();
  await expect(page.getByText('Submitted').first()).toBeVisible();

  await page.reload();
  await page.getByText('CLM-E2E-1').click();
  await expect(page.getByText('Submitted').first()).toBeVisible();
});
```

- [ ] **Step 3: Run it against the compose stack**

Run: `docker compose up -d && cd frontend && npm run e2e`
Expected: 1 passed. (The batch is dry-run by default in the upload form, so no API key is needed and drafting completes in seconds.)

- [ ] **Step 4: Final full verification and commit**

Run from repo root: `.venv/bin/python -m pytest tests/ -q` and `cd frontend && npm test && npm run build:app && npm run build:template`
Expected: everything green; both builds succeed.

```bash
git add frontend/e2e frontend/playwright.config.ts frontend/package.json frontend/package-lock.json
git commit -m "e2e: full persistence loop — login, upload, draft, approve, reload"
```

---

## Self-Review Notes

- Spec coverage: data model + sinks (T1–T2), auth (T3), upload/validation/caps/retry (T4), worker queue + per-claim checkpoint + failure semantics (T5), worklist/audit/export/PATCH incl. demo-409 and transient-status-409 (T6), demo seeding + public endpoints (T7), frontend mutations + debounced letter saves (T8), SPA login/runs/polling/hash routing + no-PHI copy + synthetic banner (T9), Docker/compose/Railway/README (T10), Playwright persistence E2E (T11). Out-of-scope list has no tasks — correct.
- Type consistency: `run_payload`/`claim_entry` camelCase keys match `api.ts` `RunInfo`/`Claim` consumption; `WorkbenchMutations` signature identical in T8 tests, T8 App, T9 ServerApp; `claim_next_run`/`process_run` signatures consistent across T5 tests, T6/T7 usage.
- The `client` kwarg on `run_worker_loop` (used by T5's loop test) is threaded through to `process_run`.
- Playwright `getByLabel` works because LoginScreen wraps inputs in `<label>` elements.
- Postgres-only features (`JSONB`, `UUID`, `nulls_last`, `SKIP LOCKED`) are why tests skip without the db container — documented in conftest.
