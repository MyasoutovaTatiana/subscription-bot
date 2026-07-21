"""uq_transactions_subscription_id_transaction_date

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-21 13:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "uq_transactions_subscription_id_transaction_date"


def upgrade() -> None:
    conn = op.get_bind()
    duplicates = conn.execute(
        sa.text(
            """
            SELECT subscription_id, transaction_date, COUNT(*) AS cnt
            FROM transactions
            WHERE subscription_id IS NOT NULL
            GROUP BY subscription_id, transaction_date
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC, subscription_id, transaction_date
            """
        )
    ).fetchall()
    if duplicates:
        sample = ", ".join(
            f"(subscription_id={row.subscription_id}, "
            f"transaction_date={row.transaction_date}, count={row.cnt})"
            for row in duplicates[:5]
        )
        raise RuntimeError(
            "Refusing to create "
            f"{INDEX_NAME}: found duplicate charge periods. "
            "Delete or merge duplicates manually before re-running. "
            f"Sample: {sample}"
        )

    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.create_index(
            INDEX_NAME,
            ["subscription_id", "transaction_date"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_index(INDEX_NAME)
