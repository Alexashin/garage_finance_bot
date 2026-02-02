from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Category, CategoryKind, Operation, OperationType, User, UserRole


class Repo:
    def __init__(self, session: AsyncSession):
        self.s = session

    # ----- Users -----
    async def get_user_by_tg(self, telegram_id: int) -> User | None:
        res = await self.s.execute(
            select(User).where(User.telegram_id == telegram_id, User.is_active == True)
        )
        return res.scalar_one_or_none()

    async def count_users(self) -> int:
        res = await self.s.execute(select(func.count(User.id)))
        return int(res.scalar_one())

    async def list_users(self, active_only: bool = True) -> list[User]:
        stmt = select(User).order_by(User.created_at.asc())
        if active_only:
            stmt = stmt.where(User.is_active == True)
        res = await self.s.execute(stmt)
        return list(res.scalars().all())

    async def create_user(self, telegram_id: int, name: str, role: UserRole) -> User:
        user = User(telegram_id=telegram_id, name=name, role=role, is_active=True)
        self.s.add(user)
        await self.s.flush()
        return user

    async def delete_user(self, telegram_id: int) -> bool:
        res = await self.s.execute(select(User).where(User.telegram_id == telegram_id))
        user = res.scalar_one_or_none()
        if not user:
            return False
        user.is_active = False
        return True

    # ----- Categories -----
    async def list_categories(self, kind: CategoryKind) -> list[Category]:
        res = await self.s.execute(
            select(Category)
            .where(Category.kind == kind, Category.is_active == True)
            .order_by(Category.name.asc())
        )
        return list(res.scalars().all())

    async def get_category_by_name(
        self, kind: CategoryKind, name: str
    ) -> Category | None:
        res = await self.s.execute(
            select(Category).where(
                Category.kind == kind, Category.name == name, Category.is_active == True
            )
        )
        return res.scalar_one_or_none()

    async def ensure_default_categories(
        self, income_names: list[str], expense_names: list[str]
    ) -> None:
        for n in income_names:
            if not n:
                continue
            if not await self.get_category_by_name(CategoryKind.income, n):
                self.s.add(
                    Category(kind=CategoryKind.income, name=n.strip(), is_active=True)
                )
        for n in expense_names:
            if not n:
                continue
            if not await self.get_category_by_name(CategoryKind.expense, n):
                self.s.add(
                    Category(kind=CategoryKind.expense, name=n.strip(), is_active=True)
                )

    async def get_category(self, category_id: int) -> Category | None:
        res = await self.s.execute(select(Category).where(Category.id == category_id))
        return res.scalar_one_or_none()

    async def category_usage_count(self, category_id: int) -> int:
        res = await self.s.execute(
            select(func.count(Operation.id)).where(Operation.category_id == category_id)
        )
        return int(res.scalar_one())

    async def create_category(self, kind: CategoryKind, name: str) -> Category:
        name = (name or "").strip()
        # защита от дублей среди активных
        existing = await self.get_category_by_name(kind, name)
        if existing:
            return existing
        cat = Category(kind=kind, name=name, is_active=True)
        self.s.add(cat)
        await self.s.flush()
        return cat

    async def rename_category(
        self, category_id: int, new_name: str
    ) -> tuple[bool, str]:
        cat = await self.get_category(category_id)
        if not cat or not cat.is_active:
            return False, "Категория не найдена."

        new_name = (new_name or "").strip()
        if len(new_name) < 2:
            return False, "Слишком короткое название."

        # защита от дублей
        dup = await self.get_category_by_name(cat.kind, new_name)
        if dup and dup.id != cat.id:
            return False, "Категория с таким названием уже есть."

        cat.name = new_name
        return True, "✅ Переименовано."

    async def deactivate_category(self, category_id: int) -> tuple[bool, str]:
        cat = await self.get_category(category_id)
        if not cat or not cat.is_active:
            return False, "Категория не найдена."

        used = await self.category_usage_count(category_id)
        if used > 0:
            return (
                False,
                f"Нельзя удалить: категория используется в операциях ({used}).",
            )

        cat.is_active = False
        return True, "✅ Категория удалена."

    # ----- Operations -----
    async def add_operation(
        self,
        op_type: OperationType,
        amount: int,
        created_by_id: int,
        category_id: int | None = None,
        comment: str | None = None,
    ) -> Operation:
        op = Operation(
            op_type=op_type,
            amount=amount,
            created_by_id=created_by_id,
            category_id=category_id,
            comment=comment,
        )
        self.s.add(op)
        await self.s.flush()
        return op

    async def list_operations_filtered(
        self,
        op_types: list[OperationType] | None,
        start: datetime | None,
        end: datetime | None,
        limit: int | None = None,
        created_by_id: int | None = None,
    ) -> list[Operation]:
        """Universal operations query.

        Notes:
        - `start/end` must be timezone-aware (because `created_at` is timestamptz).
        - For worker/viewer "only my ops", pass `created_by_id`.
        """
        stmt: Select = (
            select(Operation)
            .options(
                selectinload(Operation.category),
                selectinload(Operation.created_by),
            )
            .order_by(Operation.created_at.desc())
        )

        conds = []
        if op_types:
            conds.append(Operation.op_type.in_(op_types))
        if start:
            conds.append(Operation.created_at >= start)
        if end:
            conds.append(Operation.created_at <= end)
        if created_by_id:
            conds.append(Operation.created_by_id == created_by_id)
        if conds:
            stmt = stmt.where(and_(*conds))
        if limit:
            stmt = stmt.limit(limit)

        res = await self.s.execute(stmt)
        return list(res.scalars().all())

    async def list_last_operations(
        self,
        limit: int = 20,
        op_types: list[OperationType] | None = None,
        created_by_id: int | None = None,
    ) -> list[Operation]:
        stmt = (
            select(Operation)
            .options(
                selectinload(Operation.category),
                selectinload(Operation.created_by),
            )
            .order_by(Operation.created_at.desc())
            .limit(limit)
        )
        if op_types:
            stmt = stmt.where(Operation.op_type.in_(op_types))
        if created_by_id:
            stmt = stmt.where(Operation.created_by_id == created_by_id)
        res = await self.s.execute(stmt)
        return list(res.scalars().all())

    async def sum_by_type(self, op_type: OperationType) -> int:
        res = await self.s.execute(
            select(func.coalesce(func.sum(Operation.amount), 0)).where(
                Operation.op_type == op_type
            )
        )
        return int(res.scalar_one())

    async def balance(self) -> tuple[int, int, int]:
        """Returns (balance_total, reserve_balance, available)."""
        inc = await self.sum_by_type(OperationType.income)
        exp = await self.sum_by_type(OperationType.expense)
        reserve_in = await self.sum_by_type(OperationType.reserve_in)
        reserve_out = await self.sum_by_type(OperationType.reserve_out)
        balance_total = inc - exp
        reserve_balance = reserve_in - reserve_out
        available = balance_total - reserve_balance
        return balance_total, reserve_balance, available

    async def list_operations_for_user(
        self, telegram_id: int, limit: int = 50
    ) -> list[Operation]:
        res = await self.s.execute(
            select(Operation)
            .options(
                selectinload(Operation.category),
                selectinload(Operation.created_by),
            )
            .join(User, User.id == Operation.created_by_id)
            .where(User.telegram_id == telegram_id)
            .order_by(Operation.created_at.desc())
            .limit(limit)
        )
        return list(res.scalars().all())
