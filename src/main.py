import os
import asyncio
import logging
import logging_loki
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
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

@dp.message(F.text == "/reset")
async def handle_reset(message: Message):
    sessions.clear(message.from_user.id)
    await message.answer("🔄 История очищена. Начнем сначала!")

@dp.message(F.voice)
async def handle_voice(message: Message):
    status = await message.answer("🎧 Слушаю...")
    ogg_file = f"voice_{message.voice.file_id}.ogg"
    wav_file = f"voice_{message.voice.file_id}.wav"

    try:
        file_info = await bot.get_file(message.voice.file_id)
        await bot.download_file(file_info.file_path, destination=ogg_file)

        await status.edit_text("⚡ Обработка аудио...")
        loop = asyncio.get_running_loop()

        await loop.run_in_executor(None, ai.convert_ogg_to_wav, ogg_file, wav_file)

        await status.edit_text("⏳ Распознаю речь...")
        user_text = await loop.run_in_executor(None, ai.transcribe_audio, wav_file)

        for f_path in (ogg_file, wav_file):
            if os.path.exists(f_path):
                os.remove(f_path)

        if not user_text.strip():
            await status.edit_text("Не удалось разобрать аудио.")
            return

        await status.edit_text("🧠 Ответ...")
        marked_prompt = f"[Пользователь сказал голосом]: {user_text.strip()}"

        sessions.add(message.from_user.id, "user", marked_prompt)
        ai_response = await ai.get_text_response(sessions.get_history(message.from_user.id))
        sessions.add(message.from_user.id, "assistant", ai_response)

        await status.edit_text(f"🗣 *Вы:* {user_text.strip()}\n\n{ai_response}", parse_mode="Markdown")

    except Exception as e:
        logger.exception(f"Exception handling incoming Telegram raw Voice file from user {message.from_user.id}: {e}")
        await status.edit_text("❌ Ошибка при обработке аудио.")
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

        await message.answer(ai_response, parse_mode="Markdown")
    except Exception as e:
        logger.exception(f"Exception handling structural context request from user {message.from_user.id}: {e}")
        await message.answer("❌ Произошла ошибка ИИ при ответе. Попробуйте еще раз.")

async def main():
    logger.info("Initializing Application Service Engine under active configuration profiles...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())