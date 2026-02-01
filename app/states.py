from aiogram.fsm.state import State, StatesGroup


class IncomeFlow(StatesGroup):
    amount = State()
    category = State()
    comment = State()
    confirm = State()


class ExpenseFlow(StatesGroup):
    amount = State()
    category = State()
    comment = State()
    confirm = State()


class ReserveFlow(StatesGroup):
    add_amount = State()
    remove_amount = State()


class ReportFlow(StatesGroup):
    kind = State()
    period = State()
    custom = State()


class UserAdminFlow(StatesGroup):
    add_id = State()
    add_name = State()
    add_role = State()
    del_id = State()
