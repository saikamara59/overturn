"""Persistence model: runs (the job queue), claims (per-denial checkpoint),
audit_events (DB implementation of the package's audit protocols)."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
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
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orgs.id"), index=True, default=None
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
