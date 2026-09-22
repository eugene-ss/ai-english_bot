from aiogram.fsm.state import State, StatesGroup


class DialogFlow(StatesGroup):
    """Режим ролевого диалога."""

    choosing = State()
    talking = State()
