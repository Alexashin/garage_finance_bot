"""init

Revision ID: 0001_init
Revises: 
Create Date: 2026-02-02

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enums
    user_role = sa.Enum("owner", "viewer", "worker", name="user_role")
    category_kind = sa.Enum("income", "expense", name="category_kind")
    operation_type = sa.Enum("income", "expense", "reserve_in", "reserve_out", name="operation_type")

    user_role.create(op.get_bind(), checkfirst=True)
    category_kind.create(op.get_bind(), checkfirst=True)
    operation_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", category_kind, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_table(
        "operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("op_type", operation_type, nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_operations_created_at", "operations", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_operations_created_at", table_name="operations")
    op.drop_table("operations")
    op.drop_table("categories")
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_table("users")

    sa.Enum(name="operation_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="category_kind").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)
