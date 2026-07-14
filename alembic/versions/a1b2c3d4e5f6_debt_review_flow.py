"""debt_review_flow

Revision ID: a1b2c3d4e5f6
Revises: 20fb5ceb0ab9
Create Date: 2026-07-14 13:20:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "20fb5ceb0ab9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("debts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("share_token", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("payer_telegram_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("payment_reported_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("review_remind_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(batch_op.f("ix_debts_share_token"), ["share_token"], unique=True)
        batch_op.create_index(batch_op.f("ix_debts_payer_telegram_id"), ["payer_telegram_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_debts_review_remind_at"), ["review_remind_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("debts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_debts_review_remind_at"))
        batch_op.drop_index(batch_op.f("ix_debts_payer_telegram_id"))
        batch_op.drop_index(batch_op.f("ix_debts_share_token"))
        batch_op.drop_column("review_remind_at")
        batch_op.drop_column("payment_reported_at")
        batch_op.drop_column("payer_telegram_id")
        batch_op.drop_column("share_token")
