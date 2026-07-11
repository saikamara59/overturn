"""orgs.default_appeal_days + csv_mappings table"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0004_csv_mappings"
down_revision = "0003_dismiss_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orgs", sa.Column("default_appeal_days", sa.Integer(),
                                    nullable=False, server_default="90"))
    op.create_table(
        "csv_mappings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True),
                  sa.ForeignKey("orgs.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False, server_default="Mapping"),
        sa.Column("header_signature", sa.String(), nullable=False),
        sa.Column("headers", JSONB, nullable=False),
        sa.Column("mapping", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("org_id", "header_signature"),
    )


def downgrade() -> None:
    op.drop_table("csv_mappings")
    op.drop_column("orgs", "default_appeal_days")
