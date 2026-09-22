import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.types import CallbackQuery, Message

from src.config import settings
from src.core import (
    BusyError,
    LLMUnavailableError,
    LessonReply,
    NothingToExplainError,
    ThrottledError,
    sessions,
    tutor,
)
from src.locale import icon, labeled, t
from src.ui.delivery import deliver
from src.ui.keyboard import get_action_keyboard
from src.ui.voice import send_voice_phrase, transcribe_voice_message, voice_too_long
from src.util import escape_html

logger = logging.getLogger("eng_bot")

# Обычный режим работает только вне сценариев: внутри диалога апдейты
# забирает dialog_handlers по состоянию FSM
router = Router(name="tutor")
router.message.filter(StateFilter(None))
router.callback_query.filter(StateFilter(None))

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
    if voice_too_long(message.voice):
        await message.answer(
            labeled("error", "voice_too_long", limit=settings.bot.max_voice_duration_s)
        )
        return

    status = await message.answer(
        labeled("voice_listening", "voice_listening_html"), parse_mode="HTML"
    )
    user_id = message.from_user.id
    chat_id = message.chat.id

    try:
        user_text = await transcribe_voice_message(bot, message.voice)
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
        await deliver_reply(status, reply, user_id, html_prefix=html_prefix, edit=True)

        # Зеркало канала: на голос отвечаем голосом сразу
        if reply.speakable:
            sent = await send_voice_phrase(bot, chat_id, user_id, reply.speakable)
            if sent is None:
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

        if action in ("ui_listen", "ui_repeat", "ui_slower"):
            speakable = await sessions.get_speakable(user_id, message.message_id)
            if not speakable:
                await callback.answer(t("callback_nothing_to_listen"), show_alert=True)
                return
            await callback.answer(t("callback_listening"))
            sent = await send_voice_phrase(
                bot, chat_id, user_id, speakable, slow=action == "ui_slower"
            )
            if sent is None:
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
