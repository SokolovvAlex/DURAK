"""add loss_by_leave to game_result enum

Revision ID: a1b2c3d4e5f6
Revises: 1fc2ef0eb454
Create Date: 2025-11-01 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '1fc2ef0eb454'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Добавляем новое значение в enum gameresultenum
    op.execute("ALTER TYPE gameresultenum ADD VALUE IF NOT EXISTS 'loss_by_leave'")


def downgrade() -> None:
    # Удаление значения из enum в PostgreSQL сложно
    # Для отката нужно будет пересоздать enum без этого значения
    # Пока оставляем пустым, так как откат enum сложен
    pass

