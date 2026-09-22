from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from src.core.dialog import Scenario
from src.locale import labeled

def get_action_keyboard(*, with_listen: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text=labeled("explain", "btn_explain"), callback_data="ui_explain"),
            InlineKeyboardButton(text=labeled("next_question", "btn_next_question"), callback_data="ui_next_question"),
        ],
    ]
    if with_listen:
        buttons.append(
            [InlineKeyboardButton(text=labeled("listen", "btn_listen"), callback_data="ui_listen")]
        )
    buttons.append(
        [
            InlineKeyboardButton(text=labeled("dialog", "btn_dialog"), callback_data="ui_dialog"),
            InlineKeyboardButton(text=labeled("reset", "btn_reset"), callback_data="ui_reset"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_voice_keyboard(*, slow: bool = False) -> InlineKeyboardMarkup:
    """Управление под голосовым сообщением — основа тренировки аудирования."""
    row = [
        InlineKeyboardButton(text=labeled("repeat", "btn_repeat"), callback_data="ui_repeat")
    ]
    if not slow:
        row.append(
            InlineKeyboardButton(text=labeled("slow", "btn_slower"), callback_data="ui_slower")
        )
    return InlineKeyboardMarkup(inline_keyboard=[row])

def get_scenario_keyboard(scenarios: list[Scenario]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"{scenario.title}", callback_data=f"dlg_start:{scenario.id}")]
        for scenario in scenarios
    ]
    buttons.append(
        [InlineKeyboardButton(text=labeled("cancel", "btn_cancel"), callback_data="dlg_cancel")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_dialog_keyboard(hints: list[str], *, slow: bool = False) -> InlineKeyboardMarkup:
    """Панель хода диалога.

    Реплика приходит голосом, текст открывается по кнопке: так ход тренирует
    аудирование, а подсказки не дают новичку замолчать.
    """
    buttons = [
        [InlineKeyboardButton(text=hint, callback_data=f"dlg_hint:{index}")]
        for index, hint in enumerate(hints)
    ]
    controls = [
        InlineKeyboardButton(text=labeled("repeat", "btn_repeat"), callback_data="dlg_repeat")
    ]
    if not slow:
        controls.append(
            InlineKeyboardButton(text=labeled("slow", "btn_slower"), callback_data="dlg_slower")
        )
    buttons.append(controls)
    buttons.append(
        [
            InlineKeyboardButton(text=labeled("show_text", "btn_show_text"), callback_data="dlg_text"),
            InlineKeyboardButton(text=labeled("finish", "btn_finish"), callback_data="dlg_finish"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)
