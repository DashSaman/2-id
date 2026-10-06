"""worker challenges

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "apple_challenges",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("apple_jobs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_apple_challenges_job_id", "apple_challenges", ["job_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_apple_challenges_job_id", table_name="apple_challenges")
    op.drop_table("apple_challenges")
