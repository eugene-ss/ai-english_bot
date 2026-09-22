from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from src.locale import labeled

def get_action_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text=labeled("explain", "btn_explain"), callback_data="ui_explain"),
            InlineKeyboardButton(text=labeled("next_question", "btn_next_question"), callback_data="ui_next_question"),
        ],
        [
            InlineKeyboardButton(text=labeled("reset", "btn_reset"), callback_data="ui_reset"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
