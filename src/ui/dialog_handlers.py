import asyncio
import logging
import time

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.config import settings
from src.core import LLMUnavailableError
from src.core.dialog import SCENARIOS, dialogs, get_scenario
from src.locale import icon, labeled, t
from src.ui.delivery import deliver
from src.ui.keyboard import (
    get_action_keyboard,
    get_dialog_keyboard,
    get_scenario_keyboard,
)
from src.ui.states import DialogFlow
from src.ui.voice import send_voice_phrase, transcribe_voice_message, voice_too_long
from src.util import escape_html

logger = logging.getLogger("eng_bot")

router = Router(name="dialog")

# Пока ход обрабатывается, повторные нажатия игнорируются: иначе двойной тап
# по подсказке отправляет две реплики подряд
_busy: set[int] = set()

async def start_dialog_menu(message: Message, state: FSMContext) -> None:
    if not settings.dialog.enabled or not SCENARIOS:
        await message.answer(labeled("error", "dialog_disabled"))
        return
    await state.set_state(DialogFlow.choosing)
    await message.answer(
        f"{icon('dialog')} {t('dialog_choose_html')}",
        parse_mode="HTML",
        reply_markup=get_scenario_keyboard(list(SCENARIOS)),
    )

@router.message(Command("dialog"))
async def handle_dialog_command(message: Message, state: FSMContext):
    await start_dialog_menu(message, state)

@router.callback_query(F.data == "ui_dialog")
async def handle_dialog_entry(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.message is not None:
        await start_dialog_menu(callback.message, state)

@router.callback_query(F.data == "dlg_cancel")
async def handle_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            t("dialog_cancelled"), reply_markup=get_action_keyboard()
        )

@router.callback_query(DialogFlow.choosing, F.data.startswith("dlg_start:"))
async def handle_scenario_chosen(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    message = callback.message
    if message is None:
        return

    scenario = get_scenario(callback.data.split(":", 1)[1])
    if scenario is None:
        await message.answer(labeled("error", "dialog_scenario_missing"))
        await state.clear()
        return

    await state.set_state(DialogFlow.talking)
    await state.set_data(
        {
            "scenario_id": scenario.id,
            "transcript": [{"speaker": "teacher", "text": scenario.opening}],
            "hints": list(scenario.hints),
            "started_at": time.monotonic(),
        }
    )

    await message.answer(
        f"{icon('dialog')} {t('dialog_started_html', title=escape_html(scenario.title), goal=escape_html(scenario.goal))}",
        parse_mode="HTML",
    )
    await _send_role_turn(
        bot, message.chat.id, callback.from_user.id, scenario.opening, list(scenario.hints)
    )

@router.callback_query(DialogFlow.talking, F.data.startswith("dlg_hint:"))
async def handle_hint(callback: CallbackQuery, state: FSMContext, bot: Bot):
    message = callback.message
    if message is None:
        await callback.answer()
        return

    data = await state.get_data()
    hints = data.get("hints", [])
    try:
        index = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    if index >= len(hints):
        await callback.answer(t("dialog_hint_expired"), show_alert=True)
        return

    await callback.answer()
    await _student_turn(bot, message, callback.from_user.id, hints[index], state)

@router.callback_query(DialogFlow.talking, F.data.in_({"dlg_repeat", "dlg_slower"}))
async def handle_repeat(callback: CallbackQuery, state: FSMContext, bot: Bot):
    message = callback.message
    if message is None:
        await callback.answer()
        return

    data = await state.get_data()
    last = _last_teacher_line(data.get("transcript", []))
    if not last:
        await callback.answer(t("callback_nothing_to_listen"), show_alert=True)
        return

    slow = callback.data == "dlg_slower"
    await callback.answer(t("callback_listening"))
    await _send_role_turn(
        bot,
        message.chat.id,
        callback.from_user.id,
        last,
        data.get("hints", []),
        slow=slow,
    )

@router.callback_query(DialogFlow.talking, F.data == "dlg_text")
async def handle_show_text(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    last = _last_teacher_line(data.get("transcript", []))
    await callback.answer(last or t("callback_nothing_to_listen"), show_alert=True)

@router.callback_query(DialogFlow.talking, F.data == "dlg_finish")
async def handle_finish_button(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.message is not None:
        await _finish_dialog(callback.message, callback.from_user.id, state)

@router.message(DialogFlow.talking, Command("stop"))
async def handle_stop_command(message: Message, state: FSMContext):
    await _finish_dialog(message, message.from_user.id, state)

@router.message(DialogFlow.talking, F.voice)
async def handle_dialog_voice(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    if voice_too_long(message.voice):
        await message.answer(
            labeled("error", "voice_too_long", limit=settings.bot.max_voice_duration_s)
        )
        return

    status = await message.answer(
        labeled("transcribing", "voice_transcribing_html"), parse_mode="HTML"
    )
    try:
        user_text = await transcribe_voice_message(bot, message.voice)
    except Exception as e:
        logger.exception(f"Dialog STT failed for user {user_id}: {e}")
        await status.edit_text(labeled("error", "voice_process_error"))
        return

    if not user_text:
        await status.edit_text(labeled("error", "voice_not_recognized"))
        return

    await status.edit_text(
        f"{icon('you_said')} {t('you_said_html', text=escape_html(user_text))}",
        parse_mode="HTML",
    )
    await _student_turn(bot, message, user_id, user_text, state)

@router.message(DialogFlow.talking, F.text & ~F.text.startswith("/"))
async def handle_dialog_text(message: Message, state: FSMContext, bot: Bot):
    await _student_turn(bot, message, message.from_user.id, message.text, state)

@router.message(DialogFlow.choosing)
async def handle_choosing_noise(message: Message):
    await message.answer(t("dialog_pick_scenario"))

async def _student_turn(
    bot: Bot, message: Message, user_id: int, text: str, state: FSMContext
) -> None:
    """Ход ученика: реплика роли без исправлений, разбор откладывается на конец."""
    if user_id in _busy:
        await message.answer(t("callback_busy"))
        return

    data = await state.get_data()
    scenario = get_scenario(data.get("scenario_id", ""))
    if scenario is None:
        await state.clear()
        await message.answer(labeled("error", "dialog_scenario_missing"))
        return

    transcript = list(data.get("transcript", []))
    transcript.append({"speaker": "student", "text": text.strip()})

    if _limit_reached(transcript, data.get("started_at")):
        await state.update_data(transcript=transcript)
        await message.answer(t("dialog_limit_reached"))
        await _finish_dialog(message, user_id, state)
        return

    _busy.add(user_id)
    try:
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        reply = await dialogs.next_turn(scenario, transcript)
    except LLMUnavailableError as e:
        logger.warning(f"Dialog turn failed for user {user_id}: {e}")
        await message.answer(labeled("error", "llm_unavailable"))
        return
    except Exception as e:
        logger.exception(f"Dialog turn crashed for user {user_id}: {e}")
        await message.answer(labeled("error", "server_error"))
        return
    finally:
        _busy.discard(user_id)

    transcript.append({"speaker": "teacher", "text": reply.text})
    hints = list(reply.hints)
    await state.update_data(transcript=transcript, hints=hints)
    await _send_role_turn(bot, message.chat.id, user_id, reply.text, hints)

async def _send_role_turn(
    bot: Bot,
    chat_id: int,
    user_id: int,
    text: str,
    hints: list[str],
    *,
    slow: bool = False,
) -> None:
    """Реплика роли уходит голосом; текст доступен по кнопке «Текст»."""
    markup = get_dialog_keyboard(hints, slow=slow)
    sent = await send_voice_phrase(
        bot, chat_id, user_id, text, slow=slow, reply_markup=markup
    )
    if sent is None:
        # Без озвучки диалог продолжается текстом, чтобы ход не потерялся
        await bot.send_message(
            chat_id,
            f"{icon('teacher_speaking')} {escape_html(text)}",
            parse_mode="HTML",
            reply_markup=markup,
        )

async def _finish_dialog(message: Message, user_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    scenario = get_scenario(data.get("scenario_id", ""))
    transcript = data.get("transcript", [])
    await state.clear()

    if scenario is None or not any(
        turn.get("speaker") == "student" for turn in transcript
    ):
        await message.answer(
            t("dialog_finished_empty"), reply_markup=get_action_keyboard()
        )
        return

    status = await message.answer(
        labeled("thinking", "dialog_review_pending_html"), parse_mode="HTML"
    )
    try:
        review = await dialogs.review(scenario, transcript)
    except Exception as e:
        logger.exception(f"Dialog review failed for user {user_id}: {e}")
        await status.edit_text(labeled("error", "llm_unavailable"))
        return

    await deliver(
        status,
        review,
        html_prefix=f"{icon('explain')} {t('dialog_review_title_html')}\n\n",
        reply_markup=get_action_keyboard(),
        edit=True,
    )

def _last_teacher_line(transcript: list[dict]) -> str:
    for turn in reversed(transcript):
        if turn.get("speaker") == "teacher":
            return turn.get("text", "")
    return ""

def _limit_reached(transcript: list[dict], started_at: float | None) -> bool:
    student_turns = sum(1 for turn in transcript if turn.get("speaker") == "student")
    if student_turns >= settings.dialog.max_turns:
        return True
    if started_at is None:
        return False
    return time.monotonic() - started_at >= settings.dialog.max_duration_s
