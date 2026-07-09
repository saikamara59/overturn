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
