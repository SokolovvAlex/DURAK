"""update tx types

Revision ID: 94153b869cf9
Revises: b5a7d5966abe
Create Date: 2025-09-16 01:48:14.627417

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '94153b869cf9'
down_revision: Union[str, None] = 'b5a7d5966abe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Переименовываем старый enum
    op.execute("ALTER TYPE txtypeenum RENAME TO txtypeenum_old;")

    # Создаём новый enum (в верхнем регистре)
    op.execute(
        "CREATE TYPE txtypeenum AS ENUM ('DEPOSIT', 'WITHDRAW', 'REFERRAL_REWARD', 'PAYOUT', 'LOSS', 'ADMIN_ADJUST');"
    )

    # Меняем тип у колонки
    op.execute(
        "ALTER TABLE transactions ALTER COLUMN type TYPE txtypeenum USING UPPER(type::text)::txtypeenum;"
    )

    # Удаляем старый enum
    op.execute("DROP TYPE txtypeenum_old;")


def downgrade() -> None:
    # Переименовываем новый enum
    op.execute("ALTER TYPE txtypeenum RENAME TO txtypeenum_new;")

    # Создаём старый enum (нижний регистр + bet)
    op.execute(
        "CREATE TYPE txtypeenum AS ENUM ('deposit', 'withdraw', 'referral_reward', 'bet', 'payout', 'admin_adjust');"
    )

    # Возвращаем тип колонки (переводим в нижний регистр)
    op.execute(
        "ALTER TABLE transactions ALTER COLUMN type TYPE txtypeenum USING LOWER(type::text)::txtypeenum;"
    )

    # Удаляем новый enum
    op.execute("DROP TYPE txtypeenum_new;")