# Multi-Tenancy Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Organizations with users, Admin/Member roles, single-use invite links, per-org encrypted Anthropic keys, and hard app-level data isolation — on top of the deployed Phase 1 server.

**Architecture:** New tables (orgs/users/memberships/invites) + `runs.org_id`; auth moves from env-admin to bcrypt users with the platform admin seeded from the existing env vars; all run/claim endpoints route through org-scoping dependencies where cross-org ids 404; org Anthropic keys are Fernet-encrypted and injected per run in the worker; SPA gains Accept Invite, Org Settings, and Platform Admin screens.

**Tech Stack:** Existing Phase 1 stack + `bcrypt`, `cryptography` (Fernet).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-09-multi-tenancy-phase2-design.md`. Thin-host rule unchanged.
- Cross-org access is ALWAYS 404, never 403 (no existence leak). Disabled org → 403 on org-scoped endpoints; worker skips its runs.
- Roles exactly `admin | member`; org status exactly `active | disabled`; claim/run status values unchanged from Phase 1.
- Emails are lowercased at every boundary; unique index on `lower(email)`.
- Org API keys: encrypted with Fernet under required env `KEY_ENCRYPTION_SECRET`; responses carry `last4` only, never the key. Live upload without an org key → 422. No fallback to any platform key in the worker.
- Invite tokens: `secrets.token_urlsafe(32)`, single-use, expire 7 days; unknown → 404, used/expired → 410.
- Existing env names keep working: `ADMIN_EMAIL`/`ADMIN_PASSWORD` seed the platform-admin user + "Overturn HQ" default org at startup (idempotent).
- The public `/demo/*` endpoints and CLI/static-report surfaces must keep working unchanged; existing Phase 1 tests may be UPDATED where auth semantics changed, never deleted.
- Server tests run against Postgres via `docker compose up -d db` (skip if down). Frontend: Vitest; builds `build:app` + `build:template` must stay green.
- Every commit message ends with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: Models, crypto, config, migration 0002

**Files:**
- Modify: `pyproject.toml` (server extra += `bcrypt>=4.1`, `cryptography>=42`)
- Modify: `server/models.py` (add Org, User, Membership, Invite; `Run.org_id`)
- Create: `server/crypto.py`
- Modify: `server/config.py` (add `key_encryption_secret: str`)
- Create: `server/migrations/versions/0002_multi_tenancy.py`
- Modify: `tests/server/conftest.py` (settings fixture gains a generated Fernet secret)
- Test: `tests/server/test_crypto.py`, extend `tests/server/test_models.py`

**Interfaces:**
- Produces `server.crypto`: `hash_password(pw: str) -> str`, `verify_password(pw: str, hashed: str) -> bool` (False on malformed hash), `KeyVault(secret: str)` with `.encrypt(plain: str) -> str`, `.decrypt(token: str) -> str` (raises `ValueError` on bad token), `last4(key: str) -> str`.
- Produces models: `Org(id, name unique, status='active', anthropic_key_encrypted, anthropic_key_last4, created_at)`; `User(id, email, password_hash, is_platform_admin=False, created_at)` with unique index `uq_users_email_lower` on `lower(email)`; `Membership(id, user_id, org_id, role, created_at, UniqueConstraint(user_id, org_id))`; `Invite(id, token unique, org_id, role, email nullable, created_by, created_at, expires_at, used_at, used_by)`; `Run.org_id` (fk orgs, nullable in Python model default None — NOT NULL enforced by migration after backfill; new code always sets it).
- Settings gains required `key_encryption_secret: str`.

- [ ] **Step 1: Deps + failing tests**

In `pyproject.toml` server extra, append:

```toml
    "bcrypt>=4.1",
    "cryptography>=42",
```

Run: `.venv/bin/pip install -e ".[dev,server]"`

In `tests/server/conftest.py`, add to the top: `from cryptography.fernet import Fernet` and inside the `settings` fixture add the field:

```python
        key_encryption_secret=Fernet.generate_key().decode(),
```

`tests/server/test_crypto.py`:

```python
import pytest
from cryptography.fernet import Fernet

from server.crypto import KeyVault, hash_password, last4, verify_password


def test_password_hash_roundtrip():
    h = hash_password("s3cret-pw")
    assert h != "s3cret-pw"
    assert verify_password("s3cret-pw", h)
    assert not verify_password("wrong", h)


def test_verify_password_malformed_hash_is_false():
    assert not verify_password("x", "not-a-bcrypt-hash")


def test_keyvault_roundtrip_and_bad_token():
    vault = KeyVault(Fernet.generate_key().decode())
    token = vault.encrypt("sk-ant-abc123xyz")
    assert token != "sk-ant-abc123xyz"
    assert vault.decrypt(token) == "sk-ant-abc123xyz"
    with pytest.raises(ValueError):
        vault.decrypt("garbage")


def test_last4():
    assert last4("sk-ant-abc123wxyz") == "wxyz"
```

Append to `tests/server/test_models.py`:

```python
def test_org_user_membership_invite_roundtrip(session_factory):
    import uuid
    from datetime import timedelta

    from server.models import Invite, Membership, Org, User

    with session_factory() as s:
        org = Org(name="Acme RCM")
        user = User(email="a@b.c", password_hash="h")
        s.add_all([org, user])
        s.flush()
        s.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
        s.add(Invite(
            token="tok123", org_id=org.id, role="member",
            created_by=user.id, expires_at=utcnow() + timedelta(days=7),
        ))
        s.commit()
        assert org.status == "active"
        assert org.anthropic_key_encrypted is None
        assert user.is_platform_admin is False
        inv = s.query(Invite).one()
        assert inv.used_at is None and inv.used_by is None


def test_run_carries_org_id(session_factory):
    from server.models import Org

    with session_factory() as s:
        org = Org(name="O2")
        s.add(org)
        s.flush()
        run = make_run(org_id=org.id)
        s.add(run)
        s.commit()
        assert s.query(Run).one().org_id == org.id
```

Run: `.venv/bin/python -m pytest tests/server/test_crypto.py tests/server/test_models.py -q`
Expected: FAIL (crypto module, new models missing).

- [ ] **Step 2: Implement**

`server/crypto.py`:

```python
"""Password hashing (bcrypt) and org-API-key encryption (Fernet)."""
import bcrypt
from cryptography.fernet import Fernet, InvalidToken


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def last4(key: str) -> str:
    return key[-4:]


class KeyVault:
    """Encrypts/decrypts org Anthropic keys with KEY_ENCRYPTION_SECRET."""

    def __init__(self, secret: str) -> None:
        self._fernet = Fernet(secret.encode())

    def encrypt(self, plain: str) -> str:
        return self._fernet.encrypt(plain.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except (InvalidToken, ValueError) as exc:
            raise ValueError("could not decrypt org API key") from exc
```

In `server/config.py` add the field to `Settings`:

```python
    key_encryption_secret: str
```

In `server/models.py` add (imports: `Index`, `String`, `UniqueConstraint`, `func` from sqlalchemy):

```python
class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(default="active")
    anthropic_key_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    anthropic_key_last4: Mapped[str | None] = mapped_column(String(4), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("uq_users_email_lower", func.lower(text("email")), unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str]
    password_hash: Mapped[str] = mapped_column(Text)
    is_platform_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(default="member")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token: Mapped[str] = mapped_column(unique=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(default="member")
    email: Mapped[str | None] = mapped_column(default=None)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    used_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), default=None
    )
```

(Note: `func.lower(text("email"))` needs `from sqlalchemy import text`; if the
functional index gives trouble under `create_all`, use
`Index("uq_users_email_lower", func.lower(User.__table__.c.email), unique=True)`
declared after the class instead — either is acceptable, tests must pass.)

On `Run`, add after `is_demo`:

```python
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orgs.id"), index=True, default=None
    )
```

(Python-side nullable so historical fixtures work; the DB column becomes
NOT NULL via the migration after backfill. All NEW code paths set it.)

`server/migrations/versions/0002_multi_tenancy.py` (hand-written; parent
revision is the 0001 file's id — read it from
`server/migrations/versions/0001_initial.py` and substitute; shown here as
`REV_0001`):

```python
"""multi-tenancy: orgs, users, memberships, invites, runs.org_id"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0002_multi_tenancy"
down_revision = "REV_0001"  # <- replace with the actual 0001 revision id
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orgs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("anthropic_key_encrypted", sa.Text(), nullable=True),
        sa.Column("anthropic_key_last4", sa.String(4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")],
                    unique=True)
    op.create_table(
        "memberships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("org_id", UUID(as_uuid=True),
                  sa.ForeignKey("orgs.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("role", sa.String(), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "org_id"),
    )
    op.create_table(
        "invites",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("token", sa.String(), nullable=False, unique=True),
        sa.Column("org_id", UUID(as_uuid=True),
                  sa.ForeignKey("orgs.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("role", sa.String(), nullable=False, server_default="member"),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by", UUID(as_uuid=True), sa.ForeignKey("users.id"),
                  nullable=True),
    )
    # runs.org_id: add nullable -> create + backfill default org -> NOT NULL
    op.add_column("runs", sa.Column("org_id", UUID(as_uuid=True),
                                    sa.ForeignKey("orgs.id"), nullable=True))
    op.create_index("ix_runs_org_id", "runs", ["org_id"])
    op.execute(
        "INSERT INTO orgs (id, name, status) "
        "VALUES (gen_random_uuid(), 'Overturn HQ', 'active') "
        "ON CONFLICT (name) DO NOTHING"
    )
    op.execute(
        "UPDATE runs SET org_id = (SELECT id FROM orgs WHERE name = 'Overturn HQ') "
        "WHERE org_id IS NULL"
    )
    op.alter_column("runs", "org_id", nullable=False)


def downgrade() -> None:
    op.alter_column("runs", "org_id", nullable=True)
    op.drop_index("ix_runs_org_id", table_name="runs")
    op.drop_column("runs", "org_id")
    op.drop_table("invites")
    op.drop_table("memberships")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
    op.drop_table("orgs")
```

Apply to the dev db:
Run: `DATABASE_URL=postgresql+psycopg://overturn:overturn@localhost:5433/overturn .venv/bin/alembic upgrade head`
Expected: 0002 applied. (`gen_random_uuid()` exists on Postgres 13+.)

- [ ] **Step 3: Tests pass; commit**

Run: `.venv/bin/python -m pytest tests/server/ -q` — all pass (old Run fixtures still work because the Python model default is None and `create_all` in tests creates the nullable column from the model; migration NOT NULL applies to the real DB only — this asymmetry disappears in Task 2 when fixtures gain orgs).

```bash
git add pyproject.toml server/ tests/server/
git commit -m "phase2: tenant models, crypto (bcrypt+Fernet), migration 0002"
```

---

### Task 2: Users-based auth, seeding, org-context dependencies

**Files:**
- Create: `server/seed.py`
- Modify: `server/security.py` (replace env-compare with user lookup helpers)
- Modify: `server/api/deps.py` (add `current_user`, `OrgContext`, `current_org`, `require_org_admin`, `require_platform_admin`)
- Modify: `server/api/auth.py` (login against users; richer payload)
- Modify: `server/app.py` (lifespan: always seed platform admin + default org; keep demo seeding behind `demo_mode`)
- Modify: `tests/server/conftest.py` (client fixture creates app whose lifespan seeds; add `org_factory` + `user_factory` + `login_as` helpers)
- Modify: `tests/server/test_auth.py` (update to users-based semantics)
- Test: `tests/server/test_tenancy_deps.py`

**Interfaces:**
- Produces `server.seed.seed_platform(session_factory, settings) -> None` — idempotent: ensures org "Overturn HQ", upserts platform-admin user from `settings.admin_email/admin_password` (rehash if password changed), ensures admin membership in the default org.
- Produces deps: `current_user(request, session) -> User` (401); `OrgContext` dataclass `{user: User, org: Org, role: str}`; `current_org(...) -> OrgContext` (401 no session; 403 disabled org; 401 if membership vanished); `require_org_admin(ctx) -> OrgContext` (403); `require_platform_admin(user) -> User` (403).
- Login response/`me`: `{"email", "orgId", "orgName", "role", "isPlatformAdmin"}`.
- Test helpers in conftest: `make_org(session_factory, name, **over) -> Org`; `make_user(session_factory, email, password, org=None, role="member", platform_admin=False) -> User`; `login_as(client, email, password)`.

- [ ] **Step 1: Update conftest + failing tests**

Append helpers to `tests/server/conftest.py`:

```python
def make_org(session_factory, name="Acme RCM", **over):
    from server.models import Org

    with session_factory() as s:
        org = Org(name=name, **over)
        s.add(org)
        s.commit()
        return org


def make_user(session_factory, email, password, org=None, role="member",
              platform_admin=False):
    from server.crypto import hash_password
    from server.models import Membership, User

    with session_factory() as s:
        user = User(email=email.lower(), password_hash=hash_password(password),
                    is_platform_admin=platform_admin)
        s.add(user)
        s.flush()
        if org is not None:
            s.add(Membership(user_id=user.id, org_id=org.id, role=role))
        s.commit()
        return user


def login_as(client, email, password):
    r = client.post("/api/v1/auth/login",
                    json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()
```

Rewrite `tests/server/test_auth.py`:

```python
from tests.server.conftest import login, login_as, make_org, make_user


def test_platform_admin_seeded_from_env(client):
    # `login` helper uses settings.admin_email/admin_password
    login(client)
    me = client.get("/api/v1/auth/me").json()
    assert me["email"] == "admin@example.com"
    assert me["isPlatformAdmin"] is True
    assert me["orgName"] == "Overturn HQ"
    assert me["role"] == "admin"


def test_login_wrong_password_401(client):
    r = client.post("/api/v1/auth/login",
                    json={"email": "admin@example.com", "password": "nope"})
    assert r.status_code == 401


def test_login_unknown_email_401(client):
    r = client.post("/api/v1/auth/login",
                    json={"email": "ghost@x.y", "password": "pw"})
    assert r.status_code == 401


def test_member_login_email_case_insensitive(client, session_factory):
    org = make_org(session_factory)
    make_user(session_factory, "biller@acme.com", "pw12345678", org=org)
    me = login_as(client, "BILLER@ACME.COM", "pw12345678")
    assert me["orgName"] == "Acme RCM" and me["role"] == "member"


def test_logout_clears_session(client):
    login(client)
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").status_code == 401
```

`tests/server/test_tenancy_deps.py`:

```python
from tests.server.conftest import login_as, make_org, make_user


def test_disabled_org_gets_403(client, session_factory):
    org = make_org(session_factory, name="Doomed", status="active")
    make_user(session_factory, "u@doomed.com", "pw12345678", org=org)
    login_as(client, "u@doomed.com", "pw12345678")
    from server.models import Org
    with session_factory() as s:
        s.query(Org).filter_by(name="Doomed").update({"status": "disabled"})
        s.commit()
    r = client.get("/api/v1/runs")
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"]


def test_seeding_is_idempotent(client, session_factory):
    # client fixture already ran lifespan seeding once; run it again
    from server.app import create_app  # noqa: F401  (app factory import sanity)
    from server.seed import seed_platform

    from tests.server.conftest import TEST_DATABASE_URL  # noqa: F401
    seed_platform(session_factory, client.app.state.settings)
    from server.models import Membership, Org, User
    with session_factory() as s:
        assert s.query(Org).filter_by(name="Overturn HQ").count() == 1
        assert s.query(User).filter_by(email="admin@example.com").count() == 1
        assert s.query(Membership).count() == 1
```

Run: `.venv/bin/python -m pytest tests/server/test_auth.py tests/server/test_tenancy_deps.py -q`
Expected: FAIL (login still env-based; no seeding; no me payload fields).

- [ ] **Step 2: Implement**

`server/seed.py`:

```python
"""Idempotent startup seeding: default org + platform-admin from env."""
from typing import Callable

from sqlalchemy import func, select

from server.config import Settings
from server.crypto import hash_password, verify_password
from server.models import Membership, Org, User

DEFAULT_ORG_NAME = "Overturn HQ"


def seed_platform(session_factory: Callable, settings: Settings) -> None:
    with session_factory() as session:
        org = session.scalars(
            select(Org).where(Org.name == DEFAULT_ORG_NAME)
        ).first()
        if org is None:
            org = Org(name=DEFAULT_ORG_NAME)
            session.add(org)
            session.flush()

        email = settings.admin_email.lower()
        user = session.scalars(
            select(User).where(func.lower(User.email) == email)
        ).first()
        if user is None:
            user = User(email=email,
                        password_hash=hash_password(settings.admin_password),
                        is_platform_admin=True)
            session.add(user)
            session.flush()
        else:
            if not verify_password(settings.admin_password, user.password_hash):
                user.password_hash = hash_password(settings.admin_password)
            user.is_platform_admin = True

        membership = session.scalars(
            select(Membership).where(Membership.user_id == user.id,
                                     Membership.org_id == org.id)
        ).first()
        if membership is None:
            session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
        session.commit()
```

`server/security.py` — replace the whole file:

```python
from fastapi import HTTPException, Request


def require_user_id(request: Request) -> str:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="authentication required")
    return user_id
```

(The old `require_user`/`constant_time_equals` are removed; bcrypt's
`verify_password` is the constant-time comparison now. Grep for old usages —
Task 3 rewires the routers.)

`server/api/deps.py` — extend to:

```python
import uuid
from dataclasses import dataclass
from typing import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models import Membership, Org, User
from server.security import require_user_id


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


def current_user(
    request: Request, session: Session = Depends(get_session)
) -> User:
    user = session.get(User, uuid.UUID(require_user_id(request)))
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


@dataclass
class OrgContext:
    user: User
    org: Org
    role: str


def current_org(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> OrgContext:
    org_id = request.session.get("org_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="no active organization")
    membership = session.scalars(
        select(Membership).where(Membership.user_id == user.id,
                                 Membership.org_id == uuid.UUID(org_id))
    ).first()
    if membership is None:
        raise HTTPException(status_code=401, detail="no active organization")
    org = session.get(Org, membership.org_id)
    if org is None or org.status == "disabled":
        raise HTTPException(status_code=403,
                            detail="this organization is disabled")
    return OrgContext(user=user, org=org, role=membership.role)


def require_org_admin(ctx: OrgContext = Depends(current_org)) -> OrgContext:
    if ctx.role != "admin":
        raise HTTPException(status_code=403, detail="organization admin required")
    return ctx


def require_platform_admin(user: User = Depends(current_user)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="platform admin required")
    return user
```

`server/api/auth.py` — replace:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.api.deps import OrgContext, current_org, get_session
from server.crypto import verify_password
from server.models import Membership, Org, User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: str
    password: str


def _me_payload(ctx: OrgContext) -> dict:
    return {
        "email": ctx.user.email,
        "orgId": str(ctx.org.id),
        "orgName": ctx.org.name,
        "role": ctx.role,
        "isPlatformAdmin": ctx.user.is_platform_admin,
    }


@router.post("/login")
def login(
    request: Request, body: LoginBody, session: Session = Depends(get_session)
) -> dict:
    user = session.scalars(
        select(User).where(func.lower(User.email) == body.email.lower())
    ).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    membership = session.scalars(
        select(Membership)
        .where(Membership.user_id == user.id)
        .order_by(Membership.created_at)
    ).first()
    if membership is None:
        raise HTTPException(status_code=403,
                            detail="account has no organization")
    org = session.get(Org, membership.org_id)
    request.session["user_id"] = str(user.id)
    request.session["org_id"] = str(org.id)
    return _me_payload(OrgContext(user=user, org=org, role=membership.role))


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(ctx: OrgContext = Depends(current_org)) -> dict:
    return _me_payload(ctx)
```

In `server/app.py` lifespan, add seeding BEFORE demo seeding:

```python
        from server.seed import seed_platform
        seed_platform(session_factory, settings)
        if settings.demo_mode:
            from server.demo import seed_demo
            seed_demo(session_factory)
```

(Temporary note for this task only: `server/api/runs.py` and
`server/api/claims.py` still import `require_user` from `server.security`,
which no longer exists. To keep the app importable until Task 3 rewires them,
add a shim at the bottom of `server/security.py`:

```python
def require_user(request: Request) -> str:  # Phase 1 shim; removed in Task 3
    return require_user_id(request)
```

Task 3 deletes this shim.)

- [ ] **Step 3: Tests pass; commit**

Run: `.venv/bin/python -m pytest tests/server/ -q`
Expected: auth + tenancy tests pass. Phase 1 endpoint tests that only needed
a logged-in session still pass via the seeded platform admin (the `login`
helper is unchanged). Full run: `.venv/bin/python -m pytest tests/ -q`.

```bash
git add server/ tests/server/
git commit -m "phase2: users-based auth, platform seeding, org-context dependencies"
```

---

### Task 3: Org scoping of runs/claims (isolation) + live-upload key gate

**Files:**
- Modify: `server/api/runs.py` (org scoping; upload sets org_id; live requires org key)
- Modify: `server/api/claims.py` (org scoping)
- Modify: `server/security.py` (delete the `require_user` shim)
- Modify: `server/worker.py` (`claim_next_run` skips disabled orgs — join)
- Test: `tests/server/test_isolation.py`; update `tests/server/test_runs_api.py` + `tests/server/test_claims_api.py` where semantics changed

**Interfaces:**
- Consumes `current_org`/`require_org_admin` from Task 2.
- Produces in `server/api/deps.py`: `scoped_run(run_id, ctx=Depends(current_org), session=...) -> Run` (404 when not in ctx.org) and `scoped_claim(claim_id, ...) -> Claim` (404 via its run's org). All run/claim routes now depend on these; upload keeps 422/413/415 semantics but ALSO: `dry_run=False` requires `ctx.org.anthropic_key_encrypted` (422 with "organization has no API key configured; upload with dry_run or add a key in Org Settings"). The old platform-key check is REMOVED.

- [ ] **Step 1: Failing isolation tests**

`tests/server/test_isolation.py`:

```python
"""THE critical Phase 2 suite: cross-org access must always 404."""
import uuid

from overturn.dryrun import DryRunClient
from server.worker import claim_next_run, process_run
from tests.server.conftest import login_as, make_org, make_user
from tests.server.test_runs_api import upload


def two_orgs_with_runs(client, session_factory):
    org_a = make_org(session_factory, name="Org A")
    org_b = make_org(session_factory, name="Org B")
    make_user(session_factory, "a@a.a", "pw12345678", org=org_a)
    make_user(session_factory, "b@b.b", "pw12345678", org=org_b)

    login_as(client, "a@a.a", "pw12345678")
    run_a = upload(client).json()["runId"]
    with session_factory() as s:
        claim_next_run(s)
    process_run(uuid.UUID(run_a), session_factory=session_factory,
                client=DryRunClient())
    claims_a = client.get(f"/api/v1/runs/{run_a}/claims").json()["claims"]

    login_as(client, "b@b.b", "pw12345678")
    return run_a, claims_a


def test_foreign_run_is_404_everywhere(client, session_factory):
    run_a, claims_a = two_orgs_with_runs(client, session_factory)
    assert client.get(f"/api/v1/runs/{run_a}").status_code == 404
    assert client.get(f"/api/v1/runs/{run_a}/claims").status_code == 404
    assert client.get(f"/api/v1/runs/{run_a}/audit").status_code == 404
    assert client.get(f"/api/v1/runs/{run_a}/letters.zip").status_code == 404
    assert client.post(f"/api/v1/runs/{run_a}/retry").status_code == 404


def test_foreign_claim_is_404_everywhere(client, session_factory):
    _, claims_a = two_orgs_with_runs(client, session_factory)
    db_id = claims_a[0]["dbId"]
    assert client.get(f"/api/v1/claims/{db_id}").status_code == 404
    assert client.patch(f"/api/v1/claims/{db_id}",
                        json={"status": "submitted"}).status_code == 404
    assert client.get(f"/api/v1/claims/{db_id}/letter.md").status_code == 404


def test_runs_list_only_shows_own_org(client, session_factory):
    two_orgs_with_runs(client, session_factory)
    assert client.get("/api/v1/runs").json() == []


def test_live_upload_requires_org_key(client, session_factory):
    org = make_org(session_factory, name="Keyless")
    make_user(session_factory, "k@k.k", "pw12345678", org=org)
    login_as(client, "k@k.k", "pw12345678")
    r = upload(client, dry_run=False)
    assert r.status_code == 422
    assert "API key" in r.json()["detail"]


def test_upload_stamps_org_id(client, session_factory):
    from server.models import Run

    org = make_org(session_factory, name="Stamped")
    make_user(session_factory, "s@s.s", "pw12345678", org=org)
    login_as(client, "s@s.s", "pw12345678")
    run_id = upload(client).json()["runId"]
    with session_factory() as s:
        assert str(s.get(Run, uuid.UUID(run_id)).org_id) == str(org.id)
```

Also update the two Phase 1 test files:
- In `tests/server/test_runs_api.py::test_live_upload_without_api_key_422`,
  the platform-key semantics are gone — the seeded platform admin's org
  ("Overturn HQ") has no org key, so the test still expects 422 but the
  detail changes: assert `"API key" in r.json()["detail"]` (drop the exact
  `ANTHROPIC_API_KEY` string).
- Any test asserting the Phase 1 `me` shape updates to the Task 2 shape.

Run: `.venv/bin/python -m pytest tests/server/test_isolation.py -q`
Expected: FAIL (routes not scoped; upload doesn't stamp org).

- [ ] **Step 2: Implement**

Append to `server/api/deps.py`:

```python
def scoped_run(
    run_id: uuid.UUID,
    ctx: OrgContext = Depends(current_org),
    session: Session = Depends(get_session),
):
    from server.models import Run

    run = session.get(Run, run_id)
    if run is None or run.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="run not found")
    return run


def scoped_claim(
    claim_id: uuid.UUID,
    ctx: OrgContext = Depends(current_org),
    session: Session = Depends(get_session),
):
    from server.models import Claim

    claim = session.get(Claim, claim_id)
    if claim is None or claim.run.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="claim not found")
    return claim
```

Rewire `server/api/runs.py`:
- Replace every `_user: str = Depends(require_user)` with
  `ctx: OrgContext = Depends(current_org)` (imports from `server.api.deps`).
- `create_run`: replace the platform-key check with

```python
    if not dry_run and not ctx.org.anthropic_key_encrypted:
        raise HTTPException(
            422,
            detail=(
                "organization has no API key configured; upload with dry_run "
                "or add a key in Org Settings"
            ),
        )
```

  and stamp the run: `run = Run(..., org_id=ctx.org.id)`.
- `list_runs`: filter `.where(Run.org_id == ctx.org.id)`.
- `get_run`, `retry_run`, `run_claims`, `run_audit`, `run_letters_zip`:
  replace `get_run_or_404(session, run_id)` with the injected
  `run = Depends(scoped_run)` pattern (keep `get_run_or_404` only if still
  used by demo; demo has its own `_demo_run`). Delete `get_run_or_404` if
  unused.

Rewire `server/api/claims.py`: every route takes
`claim = Depends(scoped_claim)`; drop `get_claim_or_404`. Demo-run
protection (`claim.run.is_demo` → 409) stays — scoping doesn't replace it
because the platform admin's own org could contain the demo run.

`server/worker.py` — `claim_next_run` gains the org join:

```python
    run = session.execute(
        select(Run)
        .join(Org, Org.id == Run.org_id)
        .where(Run.status == "queued", Run.is_demo.is_(False),
               Org.status == "active")
        .order_by(Run.created_at)
        .limit(1)
        .with_for_update(skip_locked=True, of=Run)
    ).scalar_one_or_none()
```

(import `Org`; note `of=Run` so the row lock stays on runs.)

Delete the `require_user` shim from `server/security.py`.

One conftest consequence: `tests/server/test_worker.py::seed_run` creates
runs without an org — add an org there:

```python
def seed_run(session_factory, n=3, **run_over):
    from tests.server.conftest import make_org
    org = make_org(session_factory, name=f"WorkerOrg-{n}-{len(run_over)}")
    run_over.setdefault("org_id", org.id)
    ...
```

and `server/demo.py::seed_demo` must give the demo run an org: use the
default org (`seed_platform` has run in the app lifespan before demo
seeding; in tests call order may differ — make `seed_demo` create/find
"Overturn HQ" itself via `server.seed.DEFAULT_ORG_NAME` lookup-or-create).

- [ ] **Step 3: Tests pass; commit**

Run: `.venv/bin/python -m pytest tests/server/ -q` then `.venv/bin/python -m pytest tests/ -q`
Expected: all green, including updated Phase 1 tests.

```bash
git add server/ tests/server/
git commit -m "phase2: org-scoped runs/claims (cross-org 404), live-upload org-key gate"
```

---

### Task 4: Org management API — info, API key, members

**Files:**
- Create: `server/api/org.py`
- Modify: `server/app.py` (include router)
- Test: `tests/server/test_org_api.py`

**Interfaces:**
- Consumes Task 2 deps + `KeyVault`.
- Produces routes: `GET /api/v1/org` (member) → `{id, name, role, hasApiKey, apiKeyLast4}`; `PUT /api/v1/org/api-key {key}` (admin; 422 unless `key.startswith("sk-ant-") and len(key) >= 20`) → `{hasApiKey: true, apiKeyLast4}`; `DELETE /api/v1/org/api-key` (admin) → `{hasApiKey: false}`; `GET /api/v1/org/members` → `[{userId, email, role, joinedAt}]`; `PATCH /api/v1/org/members/{user_id} {role}` (admin; 404 non-member; 409 demoting last admin; 422 bad role); `DELETE /api/v1/org/members/{user_id}` (admin; 404 non-member; 409 removing last admin).
- App state gains `app.state.key_vault = KeyVault(settings.key_encryption_secret)` in `create_app`.

- [ ] **Step 1: Failing tests**

`tests/server/test_org_api.py`:

```python
from tests.server.conftest import login_as, make_org, make_user


def org_with_admin(client, session_factory, name="Acme RCM"):
    org = make_org(session_factory, name=name)
    make_user(session_factory, "boss@acme.com", "pw12345678", org=org, role="admin")
    make_user(session_factory, "biller@acme.com", "pw12345678", org=org)
    return org


def test_org_info_and_key_lifecycle(client, session_factory):
    org_with_admin(client, session_factory)
    login_as(client, "boss@acme.com", "pw12345678")

    info = client.get("/api/v1/org").json()
    assert info["name"] == "Acme RCM" and info["role"] == "admin"
    assert info["hasApiKey"] is False and info["apiKeyLast4"] is None

    assert client.put("/api/v1/org/api-key",
                      json={"key": "not-a-key"}).status_code == 422
    r = client.put("/api/v1/org/api-key",
                   json={"key": "sk-ant-test0123456789wxyz"})
    assert r.status_code == 200
    assert r.json() == {"hasApiKey": True, "apiKeyLast4": "wxyz"}

    # stored encrypted, decryptable, never equal to plaintext
    from server.models import Org
    with session_factory() as s:
        row = s.query(Org).filter_by(name="Acme RCM").one()
        assert row.anthropic_key_encrypted != "sk-ant-test0123456789wxyz"
        from server.crypto import KeyVault
        vault = KeyVault(client.app.state.settings.key_encryption_secret)
        assert vault.decrypt(row.anthropic_key_encrypted) == "sk-ant-test0123456789wxyz"

    assert client.delete("/api/v1/org/api-key").json() == {"hasApiKey": False}


def test_member_cannot_touch_key_or_members(client, session_factory):
    org_with_admin(client, session_factory)
    login_as(client, "biller@acme.com", "pw12345678")
    assert client.put("/api/v1/org/api-key",
                      json={"key": "sk-ant-test0123456789wxyz"}).status_code == 403
    assert client.get("/api/v1/org/members").status_code == 403
    assert client.get("/api/v1/org").status_code == 200  # info is member-visible


def test_member_management_and_last_admin_guard(client, session_factory):
    from server.models import User

    org_with_admin(client, session_factory)
    login_as(client, "boss@acme.com", "pw12345678")

    members = client.get("/api/v1/org/members").json()
    assert {m["email"] for m in members} == {"boss@acme.com", "biller@acme.com"}
    biller_id = next(m["userId"] for m in members if m["email"] == "biller@acme.com")
    boss_id = next(m["userId"] for m in members if m["email"] == "boss@acme.com")

    assert client.patch(f"/api/v1/org/members/{biller_id}",
                        json={"role": "admin"}).status_code == 200
    assert client.patch(f"/api/v1/org/members/{biller_id}",
                        json={"role": "member"}).status_code == 200
    # boss is the last admin now
    assert client.patch(f"/api/v1/org/members/{boss_id}",
                        json={"role": "member"}).status_code == 409
    assert client.delete(f"/api/v1/org/members/{boss_id}").status_code == 409
    assert client.delete(f"/api/v1/org/members/{biller_id}").status_code == 200
    assert client.patch(f"/api/v1/org/members/{biller_id}",
                        json={"role": "admin"}).status_code == 404
```

Run: expect FAIL (no org router).

- [ ] **Step 2: Implement**

`server/api/org.py`:

```python
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.api.deps import (
    OrgContext, current_org, get_session, require_org_admin,
)
from server.crypto import last4
from server.models import Membership, User

router = APIRouter(prefix="/org", tags=["org"])


@router.get("")
def org_info(ctx: OrgContext = Depends(current_org)) -> dict:
    return {
        "id": str(ctx.org.id),
        "name": ctx.org.name,
        "role": ctx.role,
        "hasApiKey": ctx.org.anthropic_key_encrypted is not None,
        "apiKeyLast4": ctx.org.anthropic_key_last4,
    }


class ApiKeyBody(BaseModel):
    key: str


@router.put("/api-key")
def set_api_key(
    request: Request,
    body: ApiKeyBody,
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> dict:
    key = body.key.strip()
    if not key.startswith("sk-ant-") or len(key) < 20:
        raise HTTPException(422, detail="that does not look like an Anthropic API key")
    org = session.get(type(ctx.org), ctx.org.id)
    org.anthropic_key_encrypted = request.app.state.key_vault.encrypt(key)
    org.anthropic_key_last4 = last4(key)
    return {"hasApiKey": True, "apiKeyLast4": org.anthropic_key_last4}


@router.delete("/api-key")
def clear_api_key(
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> dict:
    org = session.get(type(ctx.org), ctx.org.id)
    org.anthropic_key_encrypted = None
    org.anthropic_key_last4 = None
    return {"hasApiKey": False}


def _admin_count(session: Session, org_id: uuid.UUID) -> int:
    return len(session.scalars(
        select(Membership).where(Membership.org_id == org_id,
                                 Membership.role == "admin")
    ).all())


def _membership_or_404(session: Session, org_id: uuid.UUID,
                       user_id: uuid.UUID) -> Membership:
    m = session.scalars(
        select(Membership).where(Membership.org_id == org_id,
                                 Membership.user_id == user_id)
    ).first()
    if m is None:
        raise HTTPException(404, detail="member not found")
    return m


@router.get("/members")
def list_members(
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> list[dict]:
    rows = session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == ctx.org.id)
        .order_by(Membership.created_at)
    ).all()
    return [
        {
            "userId": str(u.id), "email": u.email, "role": m.role,
            "joinedAt": m.created_at.isoformat(),
        }
        for m, u in rows
    ]


class RoleBody(BaseModel):
    role: str


@router.patch("/members/{user_id}")
def change_role(
    user_id: uuid.UUID,
    body: RoleBody,
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> dict:
    if body.role not in ("admin", "member"):
        raise HTTPException(422, detail="role must be admin or member")
    m = _membership_or_404(session, ctx.org.id, user_id)
    if m.role == "admin" and body.role == "member" \
            and _admin_count(session, ctx.org.id) == 1:
        raise HTTPException(409, detail="cannot demote the last admin")
    m.role = body.role
    return {"userId": str(user_id), "role": m.role}


@router.delete("/members/{user_id}")
def remove_member(
    user_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> dict:
    m = _membership_or_404(session, ctx.org.id, user_id)
    if m.role == "admin" and _admin_count(session, ctx.org.id) == 1:
        raise HTTPException(409, detail="cannot remove the last admin")
    session.delete(m)
    return {"removed": str(user_id)}
```

In `server/app.py` `create_app`: after settings assignment add

```python
    from server.crypto import KeyVault
    app.state.key_vault = KeyVault(settings.key_encryption_secret)
```

and include `org.router` in the api router.

- [ ] **Step 3: Tests pass; commit**

Run: `.venv/bin/python -m pytest tests/server/ -q` — green.

```bash
git add server/ tests/server/test_org_api.py
git commit -m "phase2: org API — info, encrypted API key lifecycle, member management"
```

---

### Task 5: Invites — create/list/revoke + public accept

**Files:**
- Create: `server/api/invites.py` (both the org-admin routes and the public routes)
- Modify: `server/app.py` (include routers)
- Test: `tests/server/test_invites.py`

**Interfaces:**
- Org-admin routes: `POST /api/v1/org/invites {role, email?}` → `{id, token, inviteUrl, role, email, expiresAt}` (inviteUrl = `str(request.base_url) + "#/invite/" + token`); `GET /api/v1/org/invites` (pending: unused AND unexpired) → list of same minus token? include token (admins may re-copy) — include it; `DELETE /api/v1/org/invites/{invite_id}` (409 if used, 404 unknown/foreign-org).
- Public routes: `GET /api/v1/invites/{token}` → `{orgName, role, email, expiresAt}` | 404 unknown | 410 used/expired; `POST /api/v1/invites/{token}/accept {email, password}` → me-payload (session logged in; new user created, or existing user password-verified → 401 mismatch; 409 already a member of that org; password min 8 chars → 422).

- [ ] **Step 1: Failing tests**

`tests/server/test_invites.py`:

```python
from datetime import timedelta

from server.models import Invite, utcnow
from tests.server.conftest import login_as, make_org, make_user


def admin_org(client, session_factory, name="Acme RCM"):
    org = make_org(session_factory, name=name)
    make_user(session_factory, "boss@acme.com", "pw12345678", org=org, role="admin")
    login_as(client, "boss@acme.com", "pw12345678")
    return org


def create_invite(client, role="member", email=None):
    r = client.post("/api/v1/org/invites", json={"role": role, "email": email})
    assert r.status_code == 200, r.text
    return r.json()


def test_invite_lifecycle_new_user(client, session_factory):
    admin_org(client, session_factory)
    inv = create_invite(client, email="newbie@acme.com")
    assert "#/invite/" in inv["inviteUrl"]

    client.post("/api/v1/auth/logout")
    peek = client.get(f"/api/v1/invites/{inv['token']}").json()
    assert peek["orgName"] == "Acme RCM" and peek["role"] == "member"
    assert peek["email"] == "newbie@acme.com"

    r = client.post(f"/api/v1/invites/{inv['token']}/accept",
                    json={"email": "Newbie@acme.com", "password": "freshpw123"})
    assert r.status_code == 200
    assert r.json()["orgName"] == "Acme RCM" and r.json()["role"] == "member"
    # session live
    assert client.get("/api/v1/auth/me").json()["email"] == "newbie@acme.com"
    # single use
    assert client.get(f"/api/v1/invites/{inv['token']}").status_code == 410
    r2 = client.post(f"/api/v1/invites/{inv['token']}/accept",
                     json={"email": "x@y.z", "password": "whatever123"})
    assert r2.status_code == 410


def test_accept_existing_user_requires_their_password(client, session_factory):
    org_b = make_org(session_factory, name="Org B")
    make_user(session_factory, "veteran@x.y", "veteranpw123", org=org_b)
    admin_org(client, session_factory)
    inv = create_invite(client)
    client.post("/api/v1/auth/logout")

    r = client.post(f"/api/v1/invites/{inv['token']}/accept",
                    json={"email": "veteran@x.y", "password": "wrong"})
    assert r.status_code == 401
    r = client.post(f"/api/v1/invites/{inv['token']}/accept",
                    json={"email": "veteran@x.y", "password": "veteranpw123"})
    assert r.status_code == 200
    assert r.json()["orgName"] == "Acme RCM"


def test_accept_when_already_member_409(client, session_factory):
    org = admin_org(client, session_factory)
    make_user(session_factory, "dupe@acme.com", "pw12345678", org=org)
    inv = create_invite(client)
    client.post("/api/v1/auth/logout")
    r = client.post(f"/api/v1/invites/{inv['token']}/accept",
                    json={"email": "dupe@acme.com", "password": "pw12345678"})
    assert r.status_code == 409


def test_expired_invite_410(client, session_factory):
    admin_org(client, session_factory)
    inv = create_invite(client)
    with session_factory() as s:
        s.query(Invite).filter_by(token=inv["token"]).update(
            {"expires_at": utcnow() - timedelta(days=1)})
        s.commit()
    client.post("/api/v1/auth/logout")
    assert client.get(f"/api/v1/invites/{inv['token']}").status_code == 410


def test_unknown_token_404_and_revoke(client, session_factory):
    admin_org(client, session_factory)
    assert client.get("/api/v1/invites/nope").status_code == 404
    inv = create_invite(client)
    pending = client.get("/api/v1/org/invites").json()
    assert len(pending) == 1
    assert client.delete(f"/api/v1/org/invites/{inv['id']}").status_code == 200
    assert client.get("/api/v1/org/invites").json() == []
    assert client.get(f"/api/v1/invites/{inv['token']}").status_code == 404


def test_short_password_422(client, session_factory):
    admin_org(client, session_factory)
    inv = create_invite(client)
    client.post("/api/v1/auth/logout")
    r = client.post(f"/api/v1/invites/{inv['token']}/accept",
                    json={"email": "a@b.c", "password": "short"})
    assert r.status_code == 422
```

Run: expect FAIL.

- [ ] **Step 2: Implement**

`server/api/invites.py`:

```python
import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.api.deps import OrgContext, get_session, require_org_admin
from server.crypto import hash_password, verify_password
from server.models import Invite, Membership, Org, User, utcnow

org_router = APIRouter(prefix="/org/invites", tags=["invites"])
public_router = APIRouter(prefix="/invites", tags=["invites"])

INVITE_TTL_DAYS = 7


def _invite_payload(inv: Invite, request: Request) -> dict:
    return {
        "id": str(inv.id),
        "token": inv.token,
        "inviteUrl": f"{request.base_url}#/invite/{inv.token}",
        "role": inv.role,
        "email": inv.email,
        "expiresAt": inv.expires_at.isoformat(),
    }


class InviteBody(BaseModel):
    role: str = "member"
    email: str | None = None


@org_router.post("")
def create_invite(
    request: Request,
    body: InviteBody,
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> dict:
    if body.role not in ("admin", "member"):
        raise HTTPException(422, detail="role must be admin or member")
    inv = Invite(
        token=secrets.token_urlsafe(32),
        org_id=ctx.org.id,
        role=body.role,
        email=body.email.lower() if body.email else None,
        created_by=ctx.user.id,
        expires_at=utcnow() + timedelta(days=INVITE_TTL_DAYS),
    )
    session.add(inv)
    session.flush()
    return _invite_payload(inv, request)


@org_router.get("")
def list_invites(
    request: Request,
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> list[dict]:
    invites = session.scalars(
        select(Invite).where(
            Invite.org_id == ctx.org.id,
            Invite.used_at.is_(None),
            Invite.expires_at > utcnow(),
        ).order_by(Invite.created_at)
    ).all()
    return [_invite_payload(i, request) for i in invites]


@org_router.delete("/{invite_id}")
def revoke_invite(
    invite_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_admin),
    session: Session = Depends(get_session),
) -> dict:
    inv = session.get(Invite, invite_id)
    if inv is None or inv.org_id != ctx.org.id:
        raise HTTPException(404, detail="invite not found")
    if inv.used_at is not None:
        raise HTTPException(409, detail="invite already used")
    session.delete(inv)
    return {"revoked": str(invite_id)}


def _live_invite(session: Session, token: str) -> Invite:
    inv = session.scalars(select(Invite).where(Invite.token == token)).first()
    if inv is None:
        raise HTTPException(404, detail="invite not found")
    if inv.used_at is not None or inv.expires_at <= utcnow():
        raise HTTPException(410, detail="invite expired or already used")
    return inv


@public_router.get("/{token}")
def peek_invite(token: str, session: Session = Depends(get_session)) -> dict:
    inv = _live_invite(session, token)
    org = session.get(Org, inv.org_id)
    return {
        "orgName": org.name, "role": inv.role, "email": inv.email,
        "expiresAt": inv.expires_at.isoformat(),
    }


class AcceptBody(BaseModel):
    email: str
    password: str


@public_router.post("/{token}/accept")
def accept_invite(
    token: str,
    body: AcceptBody,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    from server.api.auth import _me_payload
    from server.api.deps import OrgContext as Ctx

    inv = _live_invite(session, token)
    if len(body.password) < 8:
        raise HTTPException(422, detail="password must be at least 8 characters")
    email = body.email.lower()

    user = session.scalars(
        select(User).where(func.lower(User.email) == email)
    ).first()
    if user is None:
        user = User(email=email, password_hash=hash_password(body.password))
        session.add(user)
        session.flush()
    else:
        if not verify_password(body.password, user.password_hash):
            raise HTTPException(
                401, detail="an account with this email exists; enter its password"
            )
        existing = session.scalars(
            select(Membership).where(Membership.user_id == user.id,
                                     Membership.org_id == inv.org_id)
        ).first()
        if existing is not None:
            raise HTTPException(409, detail="already a member of this organization")

    session.add(Membership(user_id=user.id, org_id=inv.org_id, role=inv.role))
    inv.used_at = utcnow()
    inv.used_by = user.id
    org = session.get(Org, inv.org_id)

    request.session["user_id"] = str(user.id)
    request.session["org_id"] = str(org.id)
    return _me_payload(Ctx(user=user, org=org, role=inv.role))
```

Include both routers in `server/app.py`'s api router
(`invites.org_router`, `invites.public_router`).

- [ ] **Step 3: Tests pass; commit**

Run: `.venv/bin/python -m pytest tests/server/ -q` — green.

```bash
git add server/ tests/server/test_invites.py
git commit -m "phase2: single-use invite links — create/list/revoke + public accept"
```

---

### Task 6: Platform admin API, disabled-org enforcement, worker org-key injection

**Files:**
- Create: `server/api/admin.py`
- Modify: `server/worker.py` (org key decrypt + inject; needs `key_vault`)
- Modify: `server/app.py` (include admin router)
- Test: `tests/server/test_admin_api.py`, extend `tests/server/test_worker.py`

**Interfaces:**
- Routes (`require_platform_admin`): `GET /api/v1/admin/orgs` → `[{id, name, status, members, runs}]`; `POST /api/v1/admin/orgs {name}` → `{org: {id, name, status}, inviteUrl, token}` (creates org + admin-role invite created_by the platform admin; 409 duplicate name); `PATCH /api/v1/admin/orgs/{org_id} {status}` (`active|disabled` else 422; 404 unknown).
- Worker: `process_run(run_id, *, session_factory, client=None, key_vault=None)` — when `client is None` and not `run.dry_run`: decrypt `run.org.anthropic_key_encrypted` via `key_vault` and build `anthropic.Anthropic(api_key=...)`; if org key missing/undecryptable → mark run failed with error "organization has no usable API key" without processing claims. `main()` constructs the vault from settings.

- [ ] **Step 1: Failing tests**

`tests/server/test_admin_api.py`:

```python
from tests.server.conftest import login, login_as, make_org, make_user


def test_platform_admin_gate(client, session_factory):
    org = make_org(session_factory)
    make_user(session_factory, "pleb@acme.com", "pw12345678", org=org)
    login_as(client, "pleb@acme.com", "pw12345678")
    assert client.get("/api/v1/admin/orgs").status_code == 403


def test_create_list_disable_org(client, session_factory):
    login(client)  # seeded platform admin
    r = client.post("/api/v1/admin/orgs", json={"name": "NewCo"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["org"]["name"] == "NewCo"
    assert "#/invite/" in out["inviteUrl"]
    assert client.post("/api/v1/admin/orgs",
                       json={"name": "NewCo"}).status_code == 409

    orgs = client.get("/api/v1/admin/orgs").json()
    names = {o["name"] for o in orgs}
    assert {"Overturn HQ", "NewCo"} <= names

    org_id = out["org"]["id"]
    assert client.patch(f"/api/v1/admin/orgs/{org_id}",
                        json={"status": "disabled"}).status_code == 200
    assert client.patch(f"/api/v1/admin/orgs/{org_id}",
                        json={"status": "bogus"}).status_code == 422

    # the new org's invite still works after re-enable
    client.patch(f"/api/v1/admin/orgs/{org_id}", json={"status": "active"})
    client.post("/api/v1/auth/logout")
    r = client.post(f"/api/v1/invites/{out['token']}/accept",
                    json={"email": "founder@newco.com", "password": "pw12345678"})
    assert r.status_code == 200 and r.json()["role"] == "admin"
```

Append to `tests/server/test_worker.py`:

```python
def test_live_run_uses_decrypted_org_key(session_factory, settings, monkeypatch):
    import server.worker as worker_mod
    from server.crypto import KeyVault, last4
    from server.models import Org

    vault = KeyVault(settings.key_encryption_secret)
    run_id = seed_run(session_factory, n=1, dry_run=False)
    with session_factory() as s:
        run = s.get(Run, run_id)
        org = s.get(Org, run.org_id)
        org.anthropic_key_encrypted = vault.encrypt("sk-ant-orgkey000011112222")
        org.anthropic_key_last4 = last4("sk-ant-orgkey000011112222")
        s.commit()

    captured = {}

    class FakeAnthropic:
        def __init__(self, api_key=None, **kwargs):
            captured["api_key"] = api_key
            from overturn.dryrun import DryRunClient
            self.messages = DryRunClient().messages

    monkeypatch.setattr(worker_mod.anthropic, "Anthropic", FakeAnthropic)
    with session_factory() as s:
        claim_next_run(s)
    process_run(run_id, session_factory=session_factory, key_vault=vault)
    assert captured["api_key"] == "sk-ant-orgkey000011112222"
    with session_factory() as s:
        assert s.get(Run, run_id).status == "completed"


def test_live_run_without_org_key_fails_cleanly(session_factory, settings):
    from server.crypto import KeyVault

    run_id = seed_run(session_factory, n=1, dry_run=False)
    with session_factory() as s:
        claim_next_run(s)
    process_run(run_id, session_factory=session_factory,
                key_vault=KeyVault(settings.key_encryption_secret))
    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == "failed"
        assert "API key" in run.error
        # claims untouched — retryable after a key is added
        assert all(c.status == "queued" for c in s.query(Claim).all())


def test_worker_skips_disabled_org_runs(session_factory):
    run_id = seed_run(session_factory)
    from server.models import Org
    with session_factory() as s:
        run = s.get(Run, run_id)
        s.get(Org, run.org_id).status = "disabled"
        s.commit()
    with session_factory() as s:
        assert claim_next_run(s) is None
```

Run: expect FAIL.

- [ ] **Step 2: Implement**

`server/api/admin.py`:

```python
import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.api.deps import get_session, require_platform_admin
from server.api.invites import INVITE_TTL_DAYS, _invite_payload
from server.models import Invite, Membership, Org, Run, User, utcnow

router = APIRouter(prefix="/admin", tags=["platform-admin"])


@router.get("/orgs")
def list_orgs(
    _admin: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> list[dict]:
    orgs = session.scalars(select(Org).order_by(Org.created_at)).all()
    out = []
    for org in orgs:
        members = session.scalar(
            select(func.count()).select_from(Membership)
            .where(Membership.org_id == org.id))
        runs = session.scalar(
            select(func.count()).select_from(Run).where(Run.org_id == org.id))
        out.append({
            "id": str(org.id), "name": org.name, "status": org.status,
            "members": members, "runs": runs,
        })
    return out


class OrgBody(BaseModel):
    name: str


@router.post("/orgs")
def create_org(
    request: Request,
    body: OrgBody,
    admin: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(422, detail="name required")
    if session.scalars(select(Org).where(Org.name == name)).first():
        raise HTTPException(409, detail="an organization with that name exists")
    org = Org(name=name)
    session.add(org)
    session.flush()
    inv = Invite(
        token=secrets.token_urlsafe(32), org_id=org.id, role="admin",
        created_by=admin.id, expires_at=utcnow() + timedelta(days=INVITE_TTL_DAYS),
    )
    session.add(inv)
    session.flush()
    payload = _invite_payload(inv, request)
    return {
        "org": {"id": str(org.id), "name": org.name, "status": org.status},
        "inviteUrl": payload["inviteUrl"],
        "token": inv.token,
    }


class StatusBody(BaseModel):
    status: str


@router.patch("/orgs/{org_id}")
def set_org_status(
    org_id: uuid.UUID,
    body: StatusBody,
    _admin: User = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict:
    if body.status not in ("active", "disabled"):
        raise HTTPException(422, detail="status must be active or disabled")
    org = session.get(Org, org_id)
    if org is None:
        raise HTTPException(404, detail="org not found")
    org.status = body.status
    return {"id": str(org.id), "status": org.status}
```

`server/worker.py` changes:
- `import anthropic` at top.
- Signature: `def process_run(run_id, *, session_factory, client=None, key_vault=None)`.
- `_build_agent(run, session_factory, client=None, key_vault=None)`:

```python
def _build_agent(run, session_factory, client=None, key_vault=None):
    kwargs: dict = {
        "audit_sink": DbAuditSink(session_factory, run.id),
        "invocation_tracker": DbInvocationTracker(session_factory, run.id),
    }
    if client is not None:
        kwargs["client"] = client
    elif run.dry_run:
        kwargs["client"] = DryRunClient()
    else:
        org = _org_of(run, session_factory)
        if org is None or not org.anthropic_key_encrypted or key_vault is None:
            raise OrgKeyError("organization has no usable API key")
        try:
            api_key = key_vault.decrypt(org.anthropic_key_encrypted)
        except ValueError as exc:
            raise OrgKeyError("organization has no usable API key") from exc
        kwargs["client"] = anthropic.Anthropic(api_key=api_key)
    return AppealAgent(**kwargs)
```

with

```python
class OrgKeyError(RuntimeError):
    pass


def _org_of(run, session_factory):
    from server.models import Org
    with session_factory() as s:
        return s.get(Org, run.org_id)
```

- In `process_run`, wrap agent construction:

```python
        try:
            agent = _build_agent(run, session_factory, client, key_vault)
        except OrgKeyError as exc:
            run.status = "failed"
            run.error = str(exc)
            run.finished_at = utcnow()
            session.commit()
            return
```

- `run_worker_loop(..., key_vault=None)` threads it; `main()` builds
  `KeyVault(settings.key_encryption_secret)` and passes it.

Include `admin.router` in `server/app.py`.

- [ ] **Step 3: Tests pass; commit**

Run: `.venv/bin/python -m pytest tests/ -q` — full suite green.

```bash
git add server/ tests/server/
git commit -m "phase2: platform-admin org provisioning; worker injects per-org keys"
```

---

### Task 7: SPA — me shape, role-gated nav shell, Accept Invite screen

**Files:**
- Modify: `frontend/src/app/api.ts` (MeInfo type; org/invite/admin endpoints)
- Modify: `frontend/src/app/ServerApp.tsx` (MeInfo state; `#/invite/<token>` public route; nav bar with Org Settings / Admin / Log out links; org name in top area)
- Create: `frontend/src/app/AcceptInviteScreen.tsx`
- Test: `frontend/src/__tests__/accept-invite.test.tsx`

**Interfaces:**
- `api.ts` additions:

```ts
export interface MeInfo {
  email: string; orgId: string; orgName: string;
  role: 'admin' | 'member'; isPlatformAdmin: boolean;
}
export interface OrgInfo { id: string; name: string; role: string; hasApiKey: boolean; apiKeyLast4: string | null }
export interface MemberInfo { userId: string; email: string; role: string; joinedAt: string }
export interface InviteInfo { id: string; token: string; inviteUrl: string; role: string; email: string | null; expiresAt: string }
export interface InvitePeek { orgName: string; role: string; email: string | null; expiresAt: string }
export interface AdminOrg { id: string; name: string; status: string; members: number; runs: number }
```

  Functions: `me(): Promise<MeInfo | null>`; `login(...): Promise<MeInfo>`;
  `getOrg()`, `setOrgApiKey(key)`, `clearOrgApiKey()`, `listMembers()`,
  `setMemberRole(userId, role)`, `removeMember(userId)`, `createInvite(role, email?)`,
  `listInvites()`, `revokeInvite(id)`, `peekInvite(token)`,
  `acceptInvite(token, email, password): Promise<MeInfo>`,
  `adminListOrgs()`, `adminCreateOrg(name)`, `adminSetOrgStatus(id, status)`.
- `ServerApp` route additions: `#/invite/<token>` renders `AcceptInviteScreen`
  BEFORE any auth gate; on success it sets the MeInfo and navigates to `''`.
  Authenticated chrome shows `orgName`, links: Org Settings (role==='admin'),
  Admin (isPlatformAdmin), Log out — links navigate by setting
  `window.location.hash`.
- `AcceptInviteScreen({ token, onAccepted: (me: MeInfo) => void })`.

- [ ] **Step 1: Failing tests**

`frontend/src/__tests__/accept-invite.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { ServerApp } from '../app/ServerApp';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);
const ok = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

const ME = { email: 'n@a.c', orgId: 'o1', orgName: 'Acme RCM', role: 'member', isPlatformAdmin: false };

beforeEach(() => { window.location.hash = '#/invite/tok123'; });
afterEach(() => { fetchMock.mockReset(); window.location.hash = ''; });

test('invite route renders peek info and accepts', async () => {
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (url === '/api/v1/auth/me') return ok({ detail: 'x' }, 401);
    if (url === '/api/v1/invites/tok123')
      return ok({ orgName: 'Acme RCM', role: 'member', email: 'n@a.c', expiresAt: '2099-01-01' });
    if (url === '/api/v1/invites/tok123/accept' && init?.method === 'POST') return ok(ME);
    if (url === '/api/v1/runs') return ok([]);
    return ok({}, 404);
  });
  render(<ServerApp />);
  expect(await screen.findByText(/join Acme RCM/i)).toBeInTheDocument();
  // email prefilled from hint
  expect(screen.getByLabelText(/email/i)).toHaveValue('n@a.c');
  await userEvent.type(screen.getByLabelText(/password/i), 'freshpw123');
  await userEvent.click(screen.getByRole('button', { name: /join/i }));
  // lands on runs screen, org name visible in chrome
  expect(await screen.findByText('Runs')).toBeInTheDocument();
  expect(screen.getByText('Acme RCM')).toBeInTheDocument();
});

test('dead invite shows the error state', async () => {
  fetchMock.mockImplementation((url: string) => {
    if (url === '/api/v1/auth/me') return ok({ detail: 'x' }, 401);
    if (url === '/api/v1/invites/tok123') return ok({ detail: 'gone' }, 410);
    if (url === '/api/v1/demo/claims') return ok({ claims: [], audit: [], summary: { processed: 0, drafts: 0, failed: 0 }, totalBilled: 0, generatedOn: null, asOf: null, model: null });
    return ok({}, 404);
  });
  render(<ServerApp />);
  expect(await screen.findByText(/no longer valid/i)).toBeInTheDocument();
});
```

Run: `cd frontend && npx vitest run src/__tests__/accept-invite.test.tsx` — FAIL.

- [ ] **Step 2: Implement**

`api.ts`: add the types above, change `me`/`login` return types to
`MeInfo`, and add:

```ts
export const getOrg = () => request<OrgInfo>('/api/v1/org');
export const setOrgApiKey = (key: string) =>
  request<{ hasApiKey: boolean; apiKeyLast4: string }>('/api/v1/org/api-key', json('PUT', { key }));
export const clearOrgApiKey = () =>
  request<{ hasApiKey: boolean }>('/api/v1/org/api-key', { method: 'DELETE' });
export const listMembers = () => request<MemberInfo[]>('/api/v1/org/members');
export const setMemberRole = (userId: string, role: string) =>
  request<{ userId: string; role: string }>(`/api/v1/org/members/${userId}`, json('PATCH', { role }));
export const removeMember = (userId: string) =>
  request<{ removed: string }>(`/api/v1/org/members/${userId}`, { method: 'DELETE' });
export const createInvite = (role: string, email?: string) =>
  request<InviteInfo>('/api/v1/org/invites', json('POST', { role, email: email || null }));
export const listInvites = () => request<InviteInfo[]>('/api/v1/org/invites');
export const revokeInvite = (id: string) =>
  request<{ revoked: string }>(`/api/v1/org/invites/${id}`, { method: 'DELETE' });
export const peekInvite = (token: string) => request<InvitePeek>(`/api/v1/invites/${token}`);
export const acceptInvite = (token: string, email: string, password: string) =>
  request<MeInfo>(`/api/v1/invites/${token}/accept`, json('POST', { email, password }));
export const adminListOrgs = () => request<AdminOrg[]>('/api/v1/admin/orgs');
export const adminCreateOrg = (name: string) =>
  request<{ org: AdminOrg; inviteUrl: string; token: string }>('/api/v1/admin/orgs', json('POST', { name }));
export const adminSetOrgStatus = (id: string, status: string) =>
  request<{ id: string; status: string }>(`/api/v1/admin/orgs/${id}`, json('PATCH', { status }));
```

`AcceptInviteScreen.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { acceptInvite, peekInvite, type InvitePeek, type MeInfo } from './api';

export function AcceptInviteScreen({
  token, onAccepted,
}: { token: string; onAccepted: (me: MeInfo) => void }) {
  const [peek, setPeek] = useState<InvitePeek | null>(null);
  const [dead, setDead] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    peekInvite(token)
      .then((p) => { setPeek(p); if (p.email) setEmail(p.email); })
      .catch(() => setDead(true));
  }, [token]);

  if (dead) {
    return (
      <div className="detail" style={{ maxWidth: 460, margin: '48px auto' }}>
        <div className="card" style={{ padding: '24px 28px' }}>
          <div className="card-title">This invite is no longer valid</div>
          <div className="sm-note" style={{ marginTop: 8 }}>
            It may have expired or already been used. Ask your organization
            admin for a new invite link.
          </div>
        </div>
      </div>
    );
  }
  if (!peek) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      onAccepted(await acceptInvite(token, email, password));
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  };

  const input = {
    display: 'block', width: '100%', marginTop: 4, padding: '7px 10px',
    border: '1px solid #DBD8D1', borderRadius: 8, font: 'inherit',
  } as const;

  return (
    <div className="detail" style={{ maxWidth: 460, margin: '48px auto' }}>
      <div className="card" style={{ padding: '24px 28px' }}>
        <div className="card-title" style={{ fontSize: 17 }}>
          You're invited to join {peek.orgName}
        </div>
        <div className="sm-note" style={{ margin: '6px 0 14px' }}>
          Role: {peek.role}. Set your password to create your account (or
          enter your existing password if you already have one).
        </div>
        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <label style={{ fontSize: 12.5, color: 'var(--mut)' }}>
            Email
            <input type="email" value={email} required style={input}
                   onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label style={{ fontSize: 12.5, color: 'var(--mut)' }}>
            Password
            <input type="password" value={password} required minLength={8} style={input}
                   onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error && <div style={{ fontSize: 12.5, color: 'var(--red-fg)' }}>{error}</div>}
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? 'Joining…' : `Join ${peek.orgName}`}
          </button>
        </form>
      </div>
    </div>
  );
}
```

`ServerApp.tsx` rework (keep existing behavior; the deltas):
- `user` state type becomes `MeInfo | null | undefined`; `me()` now returns
  `MeInfo | null`.
- Route parsing gains invite: `#/invite/<token>` → `{name:'invite', token}`,
  `#/org` → `{name:'org'}`, `#/admin` → `{name:'admin'}` (org/admin screens
  render placeholders `<div>org settings placeholder</div>` /
  `<div>platform admin placeholder</div>` in THIS task; Tasks 8–9 replace).
- Invite route renders before the auth gate:

```tsx
  if (route.name === 'invite') {
    return (
      <AcceptInviteScreen
        token={route.token}
        onAccepted={(m) => { setUser(m); window.location.hash = ''; }}
      />
    );
  }
```

- Authenticated chrome (used on runs/org/admin routes): a header bar with
  `{user.orgName}` on the left, then links:

```tsx
  const chrome = (body: JSX.Element) => (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12,
                    padding: '8px 20px', borderBottom: '1px solid var(--line)',
                    fontSize: 12.5 }}>
        <span style={{ fontWeight: 650 }}>{user.orgName}</span>
        <div className="spacer" />
        {user.role === 'admin' && (
          <button type="button" className="btn"
                  onClick={() => { window.location.hash = '#/org'; }}>Org Settings</button>
        )}
        {user.isPlatformAdmin && (
          <button type="button" className="btn"
                  onClick={() => { window.location.hash = '#/admin'; }}>Admin</button>
        )}
        <button type="button" className="btn"
                onClick={() => logout().then(() => { setUser(null); window.location.hash = ''; })}>
          Log out
        </button>
      </div>
      {body}
    </div>
  );
```

  Wrap RunsScreen and the placeholders with `chrome(...)`; the run workbench
  route keeps its existing header (add org name text there too).

- [ ] **Step 3: Tests pass; build; commit**

Run: `cd frontend && npm test && npm run build:app && npm run build:template`
Expected: all green (fix any pre-existing ServerApp tests whose mocked `me`
payload must become MeInfo-shaped).

```bash
git add frontend/src
git commit -m "phase2 spa: MeInfo, role-gated chrome, accept-invite flow"
```

---

### Task 8: SPA — Org Settings screen

**Files:**
- Create: `frontend/src/app/OrgSettingsScreen.tsx`
- Modify: `frontend/src/app/ServerApp.tsx` (replace org placeholder)
- Test: `frontend/src/__tests__/org-settings.test.tsx`

**Interfaces:**
- Consumes Task 7 api functions. `OrgSettingsScreen({ onBack: () => void })` — self-loading (getOrg/listMembers/listInvites on mount).

- [ ] **Step 1: Failing tests**

`frontend/src/__tests__/org-settings.test.tsx`:

```tsx
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { OrgSettingsScreen } from '../app/OrgSettingsScreen';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);
afterEach(() => fetchMock.mockReset());
const ok = (b: unknown, s = 200) => Promise.resolve(new Response(JSON.stringify(b), { status: s }));

function wire(overrides: Record<string, unknown> = {}) {
  const base: Record<string, unknown> = {
    '/api/v1/org': { id: 'o1', name: 'Acme RCM', role: 'admin', hasApiKey: false, apiKeyLast4: null },
    '/api/v1/org/members': [
      { userId: 'u1', email: 'boss@acme.com', role: 'admin', joinedAt: '2026-07-01' },
      { userId: 'u2', email: 'biller@acme.com', role: 'member', joinedAt: '2026-07-02' },
    ],
    '/api/v1/org/invites': [],
    ...overrides,
  };
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (init?.method === 'PUT' && url === '/api/v1/org/api-key')
      return ok({ hasApiKey: true, apiKeyLast4: 'wxyz' });
    if (init?.method === 'POST' && url === '/api/v1/org/invites')
      return ok({ id: 'i1', token: 't', inviteUrl: 'http://x/#/invite/t', role: 'member', email: null, expiresAt: '2099-01-01' });
    if (url in base) return ok(base[url]);
    return ok({}, 404);
  });
}

test('renders members, sets API key, shows last4', async () => {
  wire();
  render(<OrgSettingsScreen onBack={() => {}} />);
  expect(await screen.findByText('boss@acme.com')).toBeInTheDocument();
  expect(screen.getByText('biller@acme.com')).toBeInTheDocument();

  await userEvent.type(screen.getByLabelText(/anthropic api key/i), 'sk-ant-test0123456789wxyz');
  await userEvent.click(screen.getByRole('button', { name: /save key/i }));
  expect(await screen.findByText(/wxyz/)).toBeInTheDocument();
});

test('creates an invite and shows the copyable link', async () => {
  wire();
  render(<OrgSettingsScreen onBack={() => {}} />);
  await screen.findByText('boss@acme.com');
  await userEvent.click(screen.getByRole('button', { name: /create invite/i }));
  const link = await screen.findByDisplayValue('http://x/#/invite/t');
  expect(link).toBeInTheDocument();
});
```

Run: FAIL (screen missing).

- [ ] **Step 2: Implement**

`OrgSettingsScreen.tsx`:

```tsx
import { useCallback, useEffect, useState } from 'react';
import {
  clearOrgApiKey, createInvite, getOrg, listInvites, listMembers,
  removeMember, revokeInvite, setMemberRole, setOrgApiKey,
  type InviteInfo, type MemberInfo, type OrgInfo,
} from './api';

export function OrgSettingsScreen({ onBack }: { onBack: () => void }) {
  const [org, setOrg] = useState<OrgInfo | null>(null);
  const [members, setMembers] = useState<MemberInfo[]>([]);
  const [invites, setInvites] = useState<InviteInfo[]>([]);
  const [keyInput, setKeyInput] = useState('');
  const [inviteRole, setInviteRole] = useState('member');
  const [error, setError] = useState('');

  const refresh = useCallback(() => {
    getOrg().then(setOrg).catch((e) => setError(String(e.message ?? e)));
    listMembers().then(setMembers).catch(() => {});
    listInvites().then(setInvites).catch(() => {});
  }, []);
  useEffect(refresh, [refresh]);

  if (!org) return <div className="sm-note" style={{ padding: 24 }}>{error || 'Loading…'}</div>;

  const act = (p: Promise<unknown>) =>
    p.then(refresh).catch((e) => setError(String((e as Error).message ?? e)));

  return (
    <div className="sm"><div className="sm-inner">
      <div className="sm-head">
        <div className="sm-title">Org Settings — {org.name}</div>
        <div className="spacer" />
        <button type="button" className="sm-back" onClick={onBack}>← Back to runs</button>
      </div>
      {error && <div style={{ color: 'var(--red-fg)', fontSize: 12.5, marginTop: 8 }}>{error}</div>}

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">Anthropic API key</div>
        <div className="sm-note" style={{ marginTop: 6 }}>
          {org.hasApiKey
            ? `A key ending in ${org.apiKeyLast4} is configured — live runs bill your organization.`
            : 'No key configured — uploads run in dry-run mode (no Claude refinement).'}
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <label style={{ fontSize: 12.5, color: 'var(--mut)', flex: 1, minWidth: 260 }}>
            Anthropic API key
            <input type="password" value={keyInput} placeholder="sk-ant-…"
                   onChange={(e) => setKeyInput(e.target.value)}
                   style={{ display: 'block', width: '100%', marginTop: 4, padding: '7px 10px',
                            border: '1px solid #DBD8D1', borderRadius: 8, font: 'inherit' }} />
          </label>
          <button type="button" className="btn-primary"
                  onClick={() => act(setOrgApiKey(keyInput)).then(() => setKeyInput(''))}>
            Save key
          </button>
          {org.hasApiKey && (
            <button type="button" className="btn" onClick={() => act(clearOrgApiKey())}>
              Remove key
            </button>
          )}
        </div>
      </div>

      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-title">Members</div>
        <div style={{ marginTop: 8 }}>
          {members.map((m) => (
            <div key={m.userId} className="audit-row" style={{ gap: 14 }}>
              <div style={{ flex: 1, fontSize: 13 }}>{m.email}</div>
              <select value={m.role} style={{ font: 'inherit', fontSize: 12.5 }}
                      onChange={(e) => act(setMemberRole(m.userId, e.target.value))}>
                <option value="admin">admin</option>
                <option value="member">member</option>
              </select>
              <button type="button" className="btn" onClick={() => act(removeMember(m.userId))}>
                Remove
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-title">Invites</div>
        <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'center' }}>
          <select value={inviteRole} style={{ font: 'inherit', fontSize: 12.5 }}
                  onChange={(e) => setInviteRole(e.target.value)}>
            <option value="member">member</option>
            <option value="admin">admin</option>
          </select>
          <button type="button" className="btn-primary"
                  onClick={() => act(createInvite(inviteRole))}>
            Create invite
          </button>
        </div>
        <div style={{ marginTop: 8 }}>
          {invites.length === 0 && <div className="sm-note">No pending invites.</div>}
          {invites.map((inv) => (
            <div key={inv.id} className="audit-row" style={{ gap: 10 }}>
              <span className="pill c-blue">{inv.role}</span>
              <input readOnly value={inv.inviteUrl}
                     style={{ flex: 1, font: 'inherit', fontSize: 12, padding: '4px 8px',
                              border: '1px solid var(--line-2)', borderRadius: 6 }}
                     onFocus={(e) => e.target.select()} />
              <button type="button" className="btn"
                      onClick={() => navigator.clipboard?.writeText(inv.inviteUrl)}>
                Copy
              </button>
              <button type="button" className="btn" onClick={() => act(revokeInvite(inv.id))}>
                Revoke
              </button>
            </div>
          ))}
        </div>
        <div className="sm-note" style={{ marginTop: 8 }}>
          Invite links are single-use and expire after 7 days. Password reset:
          create a new invite for the same email.
        </div>
      </div>
    </div></div>
  );
}
```

In `ServerApp.tsx`, replace the org placeholder with
`chrome(<OrgSettingsScreen onBack={() => { window.location.hash = ''; }} />)`
(role-guard: if `user.role !== 'admin'`, redirect hash to `''`).

- [ ] **Step 3: Tests pass; commit**

Run: `cd frontend && npm test` — green.

```bash
git add frontend/src
git commit -m "phase2 spa: org settings — members, invites, API key"
```

---

### Task 9: SPA — Platform Admin screen

**Files:**
- Create: `frontend/src/app/PlatformAdminScreen.tsx`
- Modify: `frontend/src/app/ServerApp.tsx` (replace admin placeholder; guard on isPlatformAdmin)
- Test: `frontend/src/__tests__/platform-admin.test.tsx`

**Interfaces:**
- Consumes `adminListOrgs`, `adminCreateOrg`, `adminSetOrgStatus`.
- `PlatformAdminScreen({ onBack: () => void })` — self-loading.

- [ ] **Step 1: Failing tests**

`frontend/src/__tests__/platform-admin.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { PlatformAdminScreen } from '../app/PlatformAdminScreen';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);
afterEach(() => fetchMock.mockReset());
const ok = (b: unknown, s = 200) => Promise.resolve(new Response(JSON.stringify(b), { status: s }));

test('lists orgs, creates one, shows first invite link, toggles status', async () => {
  let orgs = [
    { id: 'o1', name: 'Overturn HQ', status: 'active', members: 1, runs: 3 },
  ];
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (url === '/api/v1/admin/orgs' && init?.method === 'POST') {
      orgs = [...orgs, { id: 'o2', name: 'NewCo', status: 'active', members: 0, runs: 0 }];
      return ok({ org: orgs[1], inviteUrl: 'http://x/#/invite/first', token: 'first' });
    }
    if (url === '/api/v1/admin/orgs') return ok(orgs);
    if (url.startsWith('/api/v1/admin/orgs/') && init?.method === 'PATCH')
      return ok({ id: 'o2', status: 'disabled' });
    return ok({}, 404);
  });
  render(<PlatformAdminScreen onBack={() => {}} />);
  expect(await screen.findByText('Overturn HQ')).toBeInTheDocument();

  await userEvent.type(screen.getByLabelText(/organization name/i), 'NewCo');
  await userEvent.click(screen.getByRole('button', { name: /create org/i }));
  expect(await screen.findByDisplayValue('http://x/#/invite/first')).toBeInTheDocument();
  expect(await screen.findByText('NewCo')).toBeInTheDocument();
});
```

Run: FAIL.

- [ ] **Step 2: Implement**

`PlatformAdminScreen.tsx`:

```tsx
import { useCallback, useEffect, useState } from 'react';
import {
  adminCreateOrg, adminListOrgs, adminSetOrgStatus, type AdminOrg,
} from './api';

export function PlatformAdminScreen({ onBack }: { onBack: () => void }) {
  const [orgs, setOrgs] = useState<AdminOrg[]>([]);
  const [name, setName] = useState('');
  const [lastInvite, setLastInvite] = useState('');
  const [error, setError] = useState('');

  const refresh = useCallback(() => {
    adminListOrgs().then(setOrgs).catch((e) => setError(String(e.message ?? e)));
  }, []);
  useEffect(refresh, [refresh]);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      const out = await adminCreateOrg(name);
      setLastInvite(out.inviteUrl);
      setName('');
      refresh();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  };

  return (
    <div className="sm"><div className="sm-inner">
      <div className="sm-head">
        <div className="sm-title">Platform Admin</div>
        <div className="spacer" />
        <button type="button" className="sm-back" onClick={onBack}>← Back to runs</button>
      </div>
      {error && <div style={{ color: 'var(--red-fg)', fontSize: 12.5, marginTop: 8 }}>{error}</div>}

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">Create organization</div>
        <form onSubmit={create}
              style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <label style={{ fontSize: 12.5, color: 'var(--mut)' }}>
            Organization name
            <input value={name} required onChange={(e) => setName(e.target.value)}
                   style={{ display: 'block', marginTop: 4, padding: '7px 10px',
                            border: '1px solid #DBD8D1', borderRadius: 8, font: 'inherit' }} />
          </label>
          <button type="submit" className="btn-primary">Create org</button>
        </form>
        {lastInvite && (
          <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'center' }}>
            <span className="pill c-green">first admin invite</span>
            <input readOnly value={lastInvite} onFocus={(e) => e.target.select()}
                   style={{ flex: 1, font: 'inherit', fontSize: 12, padding: '4px 8px',
                            border: '1px solid var(--line-2)', borderRadius: 6 }} />
            <button type="button" className="btn"
                    onClick={() => navigator.clipboard?.writeText(lastInvite)}>Copy</button>
          </div>
        )}
      </div>

      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-title">Organizations</div>
        <div style={{ marginTop: 8 }}>
          {orgs.map((o) => (
            <div key={o.id} className="audit-row" style={{ gap: 14 }}>
              <div style={{ flex: 1, fontSize: 13, fontWeight: 550 }}>{o.name}</div>
              <span className={`pill ${o.status === 'active' ? 'c-green' : 'c-red'}`}>{o.status}</span>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 11.5, color: 'var(--mut)' }}>
                {o.members} members · {o.runs} runs
              </div>
              <button type="button" className="btn"
                      onClick={() =>
                        adminSetOrgStatus(o.id, o.status === 'active' ? 'disabled' : 'active')
                          .then(refresh)
                          .catch((e) => setError(String((e as Error).message ?? e)))}>
                {o.status === 'active' ? 'Disable' : 'Enable'}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div></div>
  );
}
```

Wire into `ServerApp.tsx` (guard: non-platform-admin hash-redirects to `''`).

- [ ] **Step 3: Tests pass; commit**

Run: `cd frontend && npm test && npm run build:app && npm run build:template` — green.

```bash
git add frontend/src
git commit -m "phase2 spa: platform admin — provision orgs, first invites, disable"
```

---

### Task 10: E2E onboarding flow, deploy config, docs

**Files:**
- Modify: `frontend/e2e/server.spec.ts` (add the multi-tenant spec)
- Modify: `docker-compose.yml` (add `KEY_ENCRYPTION_SECRET` to the shared env anchor)
- Modify: `README.md` (env list + Phase 2 notes)
- Test: full suites + e2e

**Interfaces:**
- Consumes the running compose stack (rebuild with the new code).

- [ ] **Step 1: Compose + README**

Fernet keys must be valid urlsafe-base64 32-byte keys — do not invent one.
Generate the local-dev value with:

```bash
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

and add it to `docker-compose.yml`'s `&appenv` anchor:

```yaml
      KEY_ENCRYPTION_SECRET: <paste the generated key>
```

(It is a dev-only secret in a local compose file; production gets its own
value via Railway.)

In `README.md`: add `KEY_ENCRYPTION_SECRET` (required) to both the no-Docker
dev loop and the Railway env list, and append to the Server section:

```markdown
Multi-tenancy (Phase 2): the platform admin (`ADMIN_EMAIL`) provisions
organizations from the Admin screen and shares single-use invite links.
Each org brings its own Anthropic API key (stored encrypted with
`KEY_ENCRYPTION_SECRET`); orgs without a key run dry-run only. Data is
isolated per org.
```

- [ ] **Step 2: Add the E2E**

Append to `frontend/e2e/server.spec.ts`:

```ts
test('multi-tenant onboarding: provision org → invite → isolated workspace', async ({ page, browser }) => {
  // platform admin provisions a new org
  await page.goto('/');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.getByLabel(/email/i).fill(process.env.E2E_EMAIL ?? 'admin@example.com');
  await page.getByLabel(/password/i).fill(process.env.E2E_PASSWORD ?? 'change-me-locally');
  await page.getByRole('button', { name: /log in/i }).click();
  await page.getByRole('button', { name: 'Admin' }).click();

  const orgName = `E2E Org ${Date.now()}`;
  await page.getByLabel(/organization name/i).fill(orgName);
  await page.getByRole('button', { name: /create org/i }).click();
  const inviteUrl = await page
    .locator('input[readonly]').first().inputValue();
  expect(inviteUrl).toContain('#/invite/');

  // new user accepts in a fresh browser context (separate cookies)
  const ctx = await browser.newContext();
  const invitee = await ctx.newPage();
  await invitee.goto(inviteUrl);
  await invitee.getByLabel(/email/i).fill(`founder-${Date.now()}@e2e.test`);
  await invitee.getByLabel(/password/i).fill('freshpw123');
  await invitee.getByRole('button', { name: /join/i }).click();

  // lands in an empty, isolated org
  await expect(invitee.getByText('Runs')).toBeVisible();
  await expect(invitee.getByText(orgName)).toBeVisible();
  await expect(invitee.getByText(/No runs yet/)).toBeVisible();
  await ctx.close();
});
```

Note the `Date.now()` in the org name keeps reruns against the persistent
compose DB conflict-free (org names are unique).

- [ ] **Step 3: Rebuild stack, run everything**

```bash
docker compose up -d --build web worker
.venv/bin/python -m pytest tests/ -q
cd frontend && npm test && npm run e2e
```

Expected: pytest all green; vitest all green; e2e 2 passed (the Phase 1
persistence spec + the new onboarding spec). Note: the rebuilt web service
runs migration 0002 on start — confirm with
`docker compose logs web | grep -i alembic`.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e docker-compose.yml README.md
git commit -m "phase2: onboarding e2e, KEY_ENCRYPTION_SECRET config, docs"
```

---

## Self-Review Notes

- Spec coverage: models/crypto/migration (T1), auth+seeding+deps (T2),
  isolation + live-key gate (T3 — the critical suite), org API (T4), invites
  incl. existing-user/409/410 semantics (T5), platform admin + worker
  key-injection + disabled-org skip (T6), SPA invite flow + role-gated
  chrome (T7), org settings (T8), platform admin screen (T9), e2e +
  config + docs (T10). Out-of-scope items have no tasks.
- Type consistency: `MeInfo` shape identical in auth.py `_me_payload`,
  api.ts, and tests; `OrgContext(user, org, role)` used consistently;
  `process_run(..., key_vault=)` threaded through `run_worker_loop` and
  `main()`; `_invite_payload` shared by invites and admin routers.
- Known interaction: `login` conftest helper works across all tasks because
  Task 2 seeds the platform admin with the same env-derived credentials.
- T3 explicitly lists the Phase 1 test updates (upload 422 detail, me shape)
  — updates, not deletions, per global constraints.
