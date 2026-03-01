"""add counterparties and monthly expenses

Revision ID: selfxcdddasd
Revises: ef0b03da9fc1
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa


revision = "selfxcdddasd"
down_revision = "ef0b03da9fc1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "counterparties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_counterparties_name", "counterparties", ["name"])

    op.add_column(
        "operations", sa.Column("counterparty_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_operations_counterparty_id",
        "operations",
        "counterparties",
        ["counterparty_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "monthly_expenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("day_of_month", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("counterparty_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["counterparty_id"], ["counterparties.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_monthly_expenses_title", "monthly_expenses", ["title"])


def downgrade() -> None:
    op.drop_index("ix_monthly_expenses_title", table_name="monthly_expenses")
    op.drop_table("monthly_expenses")

    op.drop_constraint(
        "fk_operations_counterparty_id", "operations", type_="foreignkey"
    )
    op.drop_column("operations", "counterparty_id")

    op.drop_index("ix_counterparties_name", table_name="counterparties")
    op.drop_table("counterparties")
