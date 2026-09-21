import os
import asyncio
import logging
import logging_loki
import re
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from src.config import settings
from src.providers import ai, sessions

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("eng_bot")

if settings.loki_url:
    auth = None
    if settings.loki_user and settings.loki_password.get_secret_value():
        auth = (settings.loki_user, settings.loki_password.get_secret_value())

    loki_handler = logging_loki.LokiHandler(
        url=settings.loki_url,
        tags={"application": "eng-learning-bot", "environment": "production"},
        auth=auth,
        version="1",
    )
    logging.getLogger("").addHandler(loki_handler)
    logger.info("Grafana Loki interceptor active.")

bot = Bot(token=settings.telegram_bot_token.get_secret_value())
dp = Dispatcher()

def get_action_keyboard() -> InlineKeyboardMarkup:
    """Генерация эргономичной и удобной клавиатуры управления обучением на русском языке"""
    buttons = [
        [
            InlineKeyboardButton(text="💡 Объяснить грамматику", callback_data="ui_explain"),
            InlineKeyboardButton(text="⏭️ Другой вопрос", callback_data="ui_next_question")
        ],
        [
            InlineKeyboardButton(text="🔄 Очистить контекст и начать заново", callback_data="ui_reset")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def escape_html(text: str) -> str:
    """Безопасное экранирование спецсимволов HTML перед отправкой в Telegram сервер"""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Преобразуем базовые маркеры **жирного** текста из LLM в валидный HTML <b>
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    # Преобразуем маркеры _курсива_ из LLM в валидный HTML <i>
    text = re.sub(r"_(.*?)_", r"<i>\1</i>", text)
    return text

@dp.callback_query(F.data.startswith("ui_"))
async def handle_ui_callbacks(callback: CallbackQuery):
    """Обработка всех интерактивных нажатий меню"""
    user_id = callback.from_user.id
    action = callback.data

    if action == "ui_reset":
        sessions.clear(user_id)
        await callback.message.answer("🔄 <b>Наша история обучения успешно сброшена!</b> Напишите или скажите что-нибудь для начала нового урока.", parse_mode="HTML")
        await callback.answer("Контекст очищен")

    elif action == "ui_explain":
        await bot.send_chat_action(chat_id=callback.message.chat.id, action="typing")
        sessions.add(user_id, "user", "Пожалуйста, объясни подробнее грамматику и сложные слова из твоего последнего сообщения на русском языке.")
        ai_response = await ai.get_text_response(sessions.get_history(user_id))
        sessions.add(user_id, "assistant", ai_response)
        await callback.message.answer(escape_html(ai_response), parse_mode="HTML", reply_markup=get_action_keyboard())
        await callback.answer()

    elif action == "ui_next_question":
        await bot.send_chat_action(chat_id=callback.message.chat.id, action="typing")
        sessions.add(user_id, "user", "Задай мне другой вопрос на английском языке, давай сменим тему.")
        ai_response = await ai.get_text_response(sessions.get_history(user_id))
        sessions.add(user_id, "assistant", ai_response)
        await callback.message.answer(escape_html(ai_response), parse_mode="HTML", reply_markup=get_action_keyboard())
        await callback.answer()

@dp.message(F.text == "/start")
async def handle_start(message: Message):
    welcome_text = (
        "👋 <b>Добро пожаловать в AI English Tutor!</b>\n\n"
        "Я твой персональный ИИ-преподаватель. Наш формат обучения — <b>50/50</b>:\n"
        "1. Ты можешь писать мне обычные <b>текстовые сообщения</b>.\n"
        "2. Или записывать <b>голосовые сообщения (Voice)</b>, чтобы тренировать Speaking!\n\n"
        "🇬🇧 <i>Let's start! Tell me, what did you do today?</i>"
    )
    await message.answer(welcome_text, parse_mode="HTML", reply_markup=get_action_keyboard())

@dp.message(F.text == "/reset")
async def handle_reset(message: Message):
    sessions.clear(message.from_user.id)
    await message.answer("🔄 История очищена. Начнем сначала!")

@dp.message(F.voice)
async def handle_voice(message: Message):
    status = await message.answer("🎧 <i>Слушаю аудиозапись...</i>", parse_mode="HTML")
    ogg_file = f"voice_{message.voice.file_id}.ogg"
    wav_file = f"voice_{message.voice.file_id}.wav"

    try:
        file_info = await bot.get_file(message.voice.file_id)
        await bot.download_file(file_info.file_path, destination=ogg_file)

        await status.edit_text("⚡ <i>Транскодирование звука...</i>", parse_mode="HTML")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, ai.convert_ogg_to_wav, ogg_file, wav_file)

        await status.edit_text("⏳ <i>Распознавание произношения...</i>", parse_mode="HTML")
        user_text = await loop.run_in_executor(None, ai.transcribe_audio, wav_file)

        for f_path in (ogg_file, wav_file):
            if os.path.exists(f_path):
                os.remove(f_path)

        if not user_text.strip():
            await status.edit_text("❌ Мне не удалось расслышать слова. Пожалуйста, повторите громче и четче.")
            return

        await status.edit_text("🧠 <i>Учитель обдумывает ответ...</i>", parse_mode="HTML")
        marked_prompt = f"[Пользователь сказал голосом]: {user_text.strip()}"

        sessions.add(message.from_user.id, "user", marked_prompt)
        ai_response = await ai.get_text_response(sessions.get_history(message.from_user.id))
        sessions.add(message.from_user.id, "assistant", ai_response)

        beautiful_response = (
            f"🗣 <b>Вы сказали:</b>\n<i>{escape_html(user_text.strip())}</i>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"{escape_html(ai_response)}"
        )
        await status.edit_text(beautiful_response, parse_mode="HTML", reply_markup=get_action_keyboard())

    except Exception as e:
        logger.exception(f"Exception handling incoming Telegram raw Voice file from user {message.from_user.id}: {e}")
        await status.edit_text("❌ Не удалось обработать голосовое сообщение. Попробуйте еще раз.")
        for f_path in (ogg_file, wav_file):
            if os.path.exists(f_path):
                os.remove(f_path)

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message):
    try:
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        user_id = message.from_user.id

        sessions.add(user_id, "user", message.text)
        ai_response = await ai.get_text_response(sessions.get_history(user_id))
        sessions.add(user_id, "assistant", ai_response)

        await message.answer(escape_html(ai_response), parse_mode="HTML", reply_markup=get_action_keyboard())
    except Exception as e:
        logger.exception(f"Exception handling structural context request from user {message.from_user.id}: {e}")
        await message.answer("❌ Извини, на сервере произошел сбой. Пожалуйста, повтори фразу.")

async def main():
    logger.info("Initializing Application Service Engine under active configuration profiles...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())