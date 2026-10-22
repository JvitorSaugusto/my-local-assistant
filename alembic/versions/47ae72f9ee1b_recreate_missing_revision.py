"""recreate missing revision

Revision ID: 47ae72f9ee1b
Revises: 4e86cd97c8f0
Create Date: 2026-10-08
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "47ae72f9ee1b"
down_revision: Union[str, Sequence[str], None] = "4e86cd97c8f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass