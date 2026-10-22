"""add code_snippet to agent_tasks

Revision ID: dfb2278e60f3
Revises: 47ae72f9ee1b
Create Date: 2026-10-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "dfb2278e60f3"
down_revision: Union[str, Sequence[str], None] = "47ae72f9ee1b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_tasks",
        sa.Column(
            "code_snippet",
            sa.Text(),
            nullable=True,
        ),
    )

    op.execute(
        "UPDATE agent_tasks SET code_snippet = '' WHERE code_snippet IS NULL"
    )

    op.alter_column(
        "agent_tasks",
        "code_snippet",
        existing_type=sa.Text(),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("agent_tasks", "code_snippet")