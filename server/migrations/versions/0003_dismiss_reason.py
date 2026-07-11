"""claims.dismiss_reason for won't-appeal dismissals"""
import sqlalchemy as sa
from alembic import op

revision = "0003_dismiss_reason"
down_revision = "0002_multi_tenancy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("claims", sa.Column("dismiss_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("claims", "dismiss_reason")
