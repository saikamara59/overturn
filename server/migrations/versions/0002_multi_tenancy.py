"""multi-tenancy: orgs, users, memberships, invites, runs.org_id"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0002_multi_tenancy"
down_revision = "78df2d15b074"
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
