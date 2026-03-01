from aiogram.fsm.state import State, StatesGroup


class IncomeFlow(StatesGroup):
    amount = State()
    category = State()
    comment = State()
    confirm = State()


class ExpenseFlow(StatesGroup):
    amount = State()
    category = State()
    counterparty = State()
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


class CategoryAdminFlow(StatesGroup):
    add_name = State()
    rename_name = State()


class CounterpartyFlow(StatesGroup):
    add_name = State()
    add_comment = State()
    edit_name = State()
    edit_comment = State()
    search = State()


class MonthlyExpenseFlow(StatesGroup):
    add_title = State()
    add_day = State()
    add_amount = State()
    add_category = State()
    add_counterparty = State()
    add_comment = State()
