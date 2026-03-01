from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from app.db import Base


class UserRole(str, enum.Enum):
    owner = "owner"
    viewer = "viewer"
    worker = "worker"


class OperationType(str, enum.Enum):
    income = "income"
    expense = "expense"
    reserve_in = "reserve_in"  # move money into reserve
    reserve_out = "reserve_out"  # move money out of reserve


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    operations: Mapped[list["Operation"]] = relationship(back_populates="created_by")


class CategoryKind(str, enum.Enum):
    income = "income"
    expense = "expense"


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[CategoryKind] = mapped_column(
        Enum(CategoryKind, name="category_kind"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class Operation(Base):
    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    op_type: Mapped[OperationType] = mapped_column(
        Enum(OperationType, name="operation_type"), nullable=False
    )
    amount: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # store in rubles (integer)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )

    counterparty_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True
    )

    created_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    created_by: Mapped[User] = relationship(back_populates="operations")
    category: Mapped[Category | None] = relationship()
    counterparty: Mapped[Optional["Counterparty"]] = relationship()


class Counterparty(Base):
    __tablename__ = "counterparties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MonthlyExpense(Base):
    __tablename__ = "monthly_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Например: "Аренда", "Подписка", "Интернет", "Закупка фреона"
    title: Mapped[str] = mapped_column(String(128), nullable=False)

    # день месяца (1..31), например 5-е число
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=False)

    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # рубли
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    counterparty_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    category: Mapped[Optional["Category"]] = relationship()
    counterparty: Mapped[Optional["Counterparty"]] = relationship()
