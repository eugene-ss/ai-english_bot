import asyncio
import uuid

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, FSInputFile

from src.config import settings
from src.locale import icon, labeled, t
from src.core import ai, sessions
from src.util import (
    convert_ogg_to_wav,
    convert_wav_to_ogg_opus,
    escape_html,
    extract_speakable_english,
    get_action_keyboard,
    remove_files,
)
from src.util.logging import setup_logging

logger = setup_logging()

bot = Bot(token=settings.telegram_bot_token.get_secret_value())
dp = Dispatcher()


async def send_teacher_voice(chat_id: int, user_id: int, speakable: str) -> bool:
    """Синтез короткой EN-фразы и отправка как Telegram voice. False — если не удалось."""
    if not speakable.strip():
        return False

    stem = f"tts_{user_id}_{uuid.uuid4().hex[:8]}"
    wav_file = f"{stem}.wav"
    ogg_file = f"{stem}.ogg"

    try:
        await bot.send_chat_action(chat_id=chat_id, action="record_voice")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, ai.synthesize_speech, speakable, wav_file)
        await loop.run_in_executor(None, convert_wav_to_ogg_opus, wav_file, ogg_file)
        await bot.send_voice(chat_id=chat_id, voice=FSInputFile(ogg_file))
        return True
    except Exception:
        logger.exception(f"TTS failed for user {user_id}")
        return False
    finally:
        remove_files(wav_file, ogg_file)


def remember_speakable(user_id: int, ai_response: str) -> str:
    speakable = extract_speakable_english(ai_response, max_chars=settings.tts.max_chars)
    if speakable:
        sessions.set_last_speakable(user_id, speakable)
    return speakable


@dp.callback_query(F.data.startswith("ui_"))
async def handle_ui_callbacks(callback: CallbackQuery):
    user_id = callback.from_user.id
    action = callback.data
    chat_id = callback.message.chat.id

    if action == "ui_reset":
        sessions.clear(user_id)
        await callback.message.answer(labeled("reset", "context_reset_html"), parse_mode="HTML")
        await callback.answer(t("callback_context_cleared"))

    elif action == "ui_explain":
        await bot.send_chat_action(chat_id=chat_id, action="typing")
        sessions.add(user_id, "user", t("prompt_explain"))
        ai_response = await ai.get_text_response(sessions.get_history(user_id))
        sessions.add(user_id, "assistant", ai_response)
        # Грамматика — только текст, без голоса и без кнопки Listen
        await callback.message.answer(
            escape_html(ai_response),
            parse_mode="HTML",
            reply_markup=get_action_keyboard(with_listen=False),
        )
        await callback.answer()

    elif action == "ui_next_question":
        await bot.send_chat_action(chat_id=chat_id, action="typing")
        sessions.add(user_id, "user", t("prompt_next_question"))
        ai_response = await ai.get_text_response(sessions.get_history(user_id))
        sessions.add(user_id, "assistant", ai_response)
        speakable = remember_speakable(user_id, ai_response)
        await callback.message.answer(
            escape_html(ai_response),
            parse_mode="HTML",
            reply_markup=get_action_keyboard(with_listen=bool(speakable)),
        )
        await callback.answer()

    elif action == "ui_listen":
        speakable = sessions.get_last_speakable(user_id)
        if not speakable:
            await callback.answer(t("callback_nothing_to_listen"), show_alert=True)
            return
        await callback.answer(t("callback_listening"))
        ok = await send_teacher_voice(chat_id, user_id, speakable)
        if not ok:
            await callback.message.answer(labeled("error", "tts_error"))

    else:
        await callback.answer()


@dp.message(F.text == "/start")
async def handle_start(message: Message):
    welcome_text = (
        f"{icon('welcome')} {t('welcome_html')}"
        f"{icon('flag_uk')} {t('welcome_start_html')}"
    )
    await message.answer(welcome_text, parse_mode="HTML", reply_markup=get_action_keyboard())


@dp.message(F.text == "/reset")
async def handle_reset(message: Message):
    sessions.clear(message.from_user.id)
    await message.answer(labeled("reset", "history_cleared"))


@dp.message(F.voice)
async def handle_voice(message: Message):
    status = await message.answer(labeled("voice_listening", "voice_listening_html"), parse_mode="HTML")
    ogg_file = f"voice_{message.voice.file_id}.ogg"
    wav_file = f"voice_{message.voice.file_id}.wav"
    user_id = message.from_user.id
    chat_id = message.chat.id

    try:
        file_info = await bot.get_file(message.voice.file_id)
        await bot.download_file(file_info.file_path, destination=ogg_file)

        await status.edit_text(labeled("transcoding", "voice_transcoding_html"), parse_mode="HTML")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, convert_ogg_to_wav, ogg_file, wav_file)

        await status.edit_text(labeled("transcribing", "voice_transcribing_html"), parse_mode="HTML")
        user_text = await loop.run_in_executor(None, ai.transcribe_audio, wav_file)

        remove_files(ogg_file, wav_file)

        if not user_text.strip():
            await status.edit_text(labeled("error", "voice_not_recognized"))
            return

        await status.edit_text(labeled("thinking", "teacher_thinking_html"), parse_mode="HTML")
        marked_prompt = t("voice_user_prefix", text=user_text.strip())

        sessions.add(user_id, "user", marked_prompt)
        ai_response = await ai.get_text_response(sessions.get_history(user_id))
        sessions.add(user_id, "assistant", ai_response)

        speakable = remember_speakable(user_id, ai_response)
        beautiful_response = (
            f"{icon('you_said')} {t('you_said_html', text=escape_html(user_text.strip()))}\n\n"
            f"{t('response_divider')}\n\n"
            f"{escape_html(ai_response)}"
        )
        await status.edit_text(
            beautiful_response,
            parse_mode="HTML",
            reply_markup=get_action_keyboard(with_listen=bool(speakable)),
        )

        # Зеркало канала: после voice сразу короткий голос учителя
        if speakable:
            ok = await send_teacher_voice(chat_id, user_id, speakable)
            if not ok:
                await message.answer(labeled("error", "tts_error"))

    except Exception as e:
        logger.exception(
            f"Exception handling incoming Telegram raw Voice file from user {user_id}: {e}"
        )
        await status.edit_text(labeled("error", "voice_process_error"))
        remove_files(ogg_file, wav_file)


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message):
    try:
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        user_id = message.from_user.id

        sessions.add(user_id, "user", message.text)
        ai_response = await ai.get_text_response(sessions.get_history(user_id))
        sessions.add(user_id, "assistant", ai_response)

        speakable = remember_speakable(user_id, ai_response)
        await message.answer(
            escape_html(ai_response),
            parse_mode="HTML",
            reply_markup=get_action_keyboard(with_listen=bool(speakable)),
        )
    except Exception as e:
        logger.exception(
            f"Exception handling structural context request from user {message.from_user.id}: {e}"
        )
        await message.answer(labeled("error", "server_error"))


async def main():
    logger.info("Initializing Application Service Engine under active configuration profiles...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
