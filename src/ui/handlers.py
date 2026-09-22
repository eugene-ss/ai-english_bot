import asyncio
import logging
import os
import tempfile
import uuid

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, Message

from src.config import settings
from src.core import (
    BusyError,
    LLMUnavailableError,
    LessonReply,
    NothingToExplainError,
    ThrottledError,
    ai,
    sessions,
    tutor,
)
from src.locale import icon, labeled, t
from src.ui.delivery import deliver
from src.ui.keyboard import get_action_keyboard
from src.util import (
    convert_ogg_to_wav,
    convert_wav_to_ogg_opus,
    escape_html,
    remove_files,
)

logger = logging.getLogger("eng_bot")

router = Router(name="tutor")

async def send_teacher_voice(bot: Bot, chat_id: int, user_id: int, speakable: str) -> bool:
    """Синтезирует короткую EN-фразу и отправляет как Telegram voice."""
    if not speakable.strip() or not ai.tts_available:
        return False

    work_dir = tempfile.mkdtemp(prefix="tts_")
    stem = uuid.uuid4().hex[:8]
    wav_file = os.path.join(work_dir, f"{stem}.wav")
    ogg_file = os.path.join(work_dir, f"{stem}.ogg")

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
        try:
            os.rmdir(work_dir)
        except OSError:
            pass

async def deliver_reply(
    message: Message,
    reply: LessonReply,
    user_id: int,
    *,
    html_prefix: str = "",
    edit: bool = False,
) -> Message:
    """Отправляет текст учителя и привязывает фразу для озвучки к сообщению."""
    sent = await deliver(
        message,
        reply.text,
        html_prefix=html_prefix,
        reply_markup=get_action_keyboard(with_listen=bool(reply.speakable)),
        edit=edit,
    )
    if reply.speakable:
        await sessions.set_speakable(user_id, sent.message_id, reply.speakable)
    return sent

@router.message(CommandStart())
async def handle_start(message: Message):
    welcome_text = (
        f"{icon('welcome')} {t('welcome_html')}"
        f"{icon('flag_uk')} {t('welcome_start_html')}"
    )
    await message.answer(
        welcome_text, parse_mode="HTML", reply_markup=get_action_keyboard()
    )

@router.message(Command("reset"))
async def handle_reset(message: Message):
    await tutor.reset(message.from_user.id)
    await message.answer(labeled("reset", "history_cleared"))

@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot):
    voice = message.voice
    if voice.duration and voice.duration > settings.bot.max_voice_duration_s:
        await message.answer(
            labeled("error", "voice_too_long", limit=settings.bot.max_voice_duration_s)
        )
        return
    if voice.file_size and voice.file_size > settings.bot.max_voice_size_bytes:
        await message.answer(
            labeled("error", "voice_too_long", limit=settings.bot.max_voice_duration_s)
        )
        return

    status = await message.answer(
        labeled("voice_listening", "voice_listening_html"), parse_mode="HTML"
    )
    user_id = message.from_user.id
    chat_id = message.chat.id

    with tempfile.TemporaryDirectory(prefix="voice_") as work_dir:
        ogg_file = os.path.join(work_dir, "incoming.ogg")
        wav_file = os.path.join(work_dir, "incoming.wav")
        try:
            file_info = await bot.get_file(voice.file_id)
            await bot.download_file(file_info.file_path, destination=ogg_file)

            await status.edit_text(
                labeled("transcoding", "voice_transcoding_html"), parse_mode="HTML"
            )
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, convert_ogg_to_wav, ogg_file, wav_file)

            await status.edit_text(
                labeled("transcribing", "voice_transcribing_html"), parse_mode="HTML"
            )
            user_text = await loop.run_in_executor(None, ai.transcribe_audio, wav_file)
            user_text = (user_text or "").strip()

            if not user_text:
                await status.edit_text(labeled("error", "voice_not_recognized"))
                return

            await status.edit_text(
                labeled("thinking", "teacher_thinking_html"), parse_mode="HTML"
            )
            reply = await tutor.reply_to_voice(user_id, user_text)

            html_prefix = (
                f"{icon('you_said')} {t('you_said_html', text=escape_html(user_text))}\n\n"
                f"{t('response_divider')}\n\n"
            )
            await deliver_reply(
                status, reply, user_id, html_prefix=html_prefix, edit=True
            )

            # Зеркало канала: на голос отвечаем голосом сразу
            if reply.speakable:
                ok = await send_teacher_voice(bot, chat_id, user_id, reply.speakable)
                if not ok:
                    await message.answer(labeled("error", "tts_error"))

        except BusyError:
            await status.edit_text(t("callback_busy"))
        except ThrottledError:
            await status.edit_text(t("callback_throttled"))
        except LLMUnavailableError as e:
            logger.warning(f"LLM unavailable for user {user_id}: {e}")
            await status.edit_text(labeled("error", "llm_unavailable"))
        except Exception as e:
            logger.exception(f"Voice handling failed for user {user_id}: {e}")
            try:
                await status.edit_text(labeled("error", "voice_process_error"))
            except Exception:
                await message.answer(labeled("error", "voice_process_error"))

@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message):
    user_id = message.from_user.id
    try:
        await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
        reply = await tutor.reply_to_text(user_id, message.text)
        await deliver_reply(message, reply, user_id)
    except BusyError:
        await message.answer(t("callback_busy"))
    except ThrottledError:
        await message.answer(t("callback_throttled"))
    except LLMUnavailableError as e:
        logger.warning(f"LLM unavailable for user {user_id}: {e}")
        await message.answer(labeled("error", "llm_unavailable"))
    except Exception as e:
        logger.exception(f"Text handling failed for user {user_id}: {e}")
        await message.answer(labeled("error", "server_error"))

@router.message(F.text.startswith("/"))
async def handle_unknown_command(message: Message):
    await message.answer(
        f"{icon('welcome')} {t('welcome_html')}",
        parse_mode="HTML",
        reply_markup=get_action_keyboard(),
    )

@router.callback_query(F.data.startswith("ui_"))
async def handle_ui_callbacks(callback: CallbackQuery, bot: Bot):
    message = callback.message
    if message is None:
        # Сообщение недоступно (слишком старое или удалено)
        await callback.answer()
        return

    user_id = callback.from_user.id
    chat_id = message.chat.id
    action = callback.data

    try:
        if action == "ui_reset":
            await tutor.reset(user_id)
            await callback.answer(t("callback_context_cleared"))
            await message.answer(
                labeled("reset", "context_reset_html"), parse_mode="HTML"
            )
            return

        if action == "ui_listen":
            speakable = await sessions.get_speakable(user_id, message.message_id)
            if not speakable:
                await callback.answer(t("callback_nothing_to_listen"), show_alert=True)
                return
            await callback.answer(t("callback_listening"))
            if not await send_teacher_voice(bot, chat_id, user_id, speakable):
                await message.answer(labeled("error", "tts_error"))
            return

        if action in ("ui_explain", "ui_next_question"):
            # Отвечаем сразу: у callback-запроса короткое окно жизни
            await callback.answer()
            await bot.send_chat_action(chat_id=chat_id, action="typing")

            if action == "ui_explain":
                reply = await tutor.explain_last(user_id)
            else:
                reply = await tutor.next_question(user_id)

            await deliver_reply(message, reply, user_id)
            return

        await callback.answer()

    except NothingToExplainError:
        await _notify(callback, message, t("callback_nothing_to_explain"), alert=True)
    except BusyError:
        await _notify(callback, message, t("callback_busy"), alert=True)
    except ThrottledError:
        await _notify(callback, message, t("callback_throttled"), alert=True)
    except LLMUnavailableError as e:
        logger.warning(f"LLM unavailable for user {user_id}: {e}")
        await message.answer(labeled("error", "llm_unavailable"))
    except Exception as e:
        logger.exception(f"Callback {action} failed for user {user_id}: {e}")
        await message.answer(labeled("error", "server_error"))

async def _notify(
    callback: CallbackQuery, message: Message, text: str, *, alert: bool = False
) -> None:
    """Сообщает пользователю причину отказа, даже если callback уже закрыт."""
    try:
        await callback.answer(text, show_alert=alert)
    except Exception:
        await message.answer(text)
