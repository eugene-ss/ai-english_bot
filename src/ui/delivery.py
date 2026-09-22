import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message

from src.util.html import escape_html, split_for_telegram, strip_markup

logger = logging.getLogger("eng_bot")

async def _send_chunk(
    message: Message,
    html_text: str,
    reply_markup: InlineKeyboardMarkup | None,
    *,
    edit: bool,
) -> Message:
    """Отправляет часть текста, при отказе разбора HTML повторяет без разметки."""
    try:
        if edit:
            return await message.edit_text(
                html_text, parse_mode="HTML", reply_markup=reply_markup
            )
        return await message.answer(
            html_text, parse_mode="HTML", reply_markup=reply_markup
        )
    except TelegramBadRequest as e:
        if "can't parse entities" not in str(e).lower():
            raise
        logger.warning(f"HTML rejected by Telegram, resending as plain text: {e}")
        plain = strip_markup(html_text)
        if edit:
            return await message.edit_text(plain, reply_markup=reply_markup)
        return await message.answer(plain, reply_markup=reply_markup)

async def deliver(
    message: Message,
    text: str,
    *,
    html_prefix: str = "",
    reply_markup: InlineKeyboardMarkup | None = None,
    edit: bool = False,
) -> Message:
    """Доставляет текст учителя, разбивая его под лимит Telegram.

    `html_prefix` вставляется в первую часть как есть — он уже валидный HTML.
    Клавиатура уходит на последнюю часть, её message_id возвращается наружу,
    чтобы привязать к нему фразу для озвучки.
    """
    body = escape_html(text)
    chunks = split_for_telegram(f"{html_prefix}{body}")
    last_index = len(chunks) - 1
    sent = message

    for index, chunk in enumerate(chunks):
        markup = reply_markup if index == last_index else None
        sent = await _send_chunk(
            message if index == 0 else sent,
            chunk,
            markup,
            edit=edit and index == 0,
        )
    return sent
