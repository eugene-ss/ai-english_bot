import asyncio
import hashlib
import logging
import os
import tempfile
import uuid

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InlineKeyboardMarkup, Message, Voice

from src.config import settings
from src.core import ai, sessions
from src.ui.keyboard import get_voice_keyboard
from src.util import convert_ogg_to_wav, convert_wav_to_ogg_opus, remove_files

logger = logging.getLogger("eng_bot")

def voice_too_long(voice: Voice) -> bool:
    if voice.duration and voice.duration > settings.bot.max_voice_duration_s:
        return True
    return bool(
        voice.file_size and voice.file_size > settings.bot.max_voice_size_bytes
    )

async def transcribe_voice_message(bot: Bot, voice: Voice) -> str:
    """Скачивает голосовое, приводит к WAV и распознаёт через Whisper."""
    with tempfile.TemporaryDirectory(prefix="voice_") as work_dir:
        ogg_file = os.path.join(work_dir, "incoming.ogg")
        wav_file = os.path.join(work_dir, "incoming.wav")

        file_info = await bot.get_file(voice.file_id)
        await bot.download_file(file_info.file_path, destination=ogg_file)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, convert_ogg_to_wav, ogg_file, wav_file)
        text = await loop.run_in_executor(None, ai.transcribe_audio, wav_file)
        return (text or "").strip()

def fingerprint(text: str, tempo: float) -> str:
    """Ключ кэша: одна и та же фраза тем же голосом и темпом синтезируется раз."""
    raw = f"{settings.tts.model_id}|{settings.tts.voice}|{tempo:.3f}|{text.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

async def send_voice_phrase(
    bot: Bot,
    chat_id: int,
    user_id: int,
    text: str,
    *,
    slow: bool = False,
    reply_markup: InlineKeyboardMarkup | None = None,
    with_controls: bool = True,
) -> Message | None:
    """Озвучивает фразу и отправляет голосовым сообщением.

    Повторная отправка той же фразы идёт через сохранённый Telegram file_id:
    это убирает и задержку синтеза, и оплату повторного вызова TTS.
    Возвращает None, если озвучить не удалось — текст к этому моменту уже у
    пользователя, поэтому диалог не прерывается.
    """
    phrase = text.strip()
    if not phrase or not ai.tts_available:
        return None

    tempo = settings.tts.slow_tempo if slow else 1.0
    key = fingerprint(phrase, tempo)
    markup = reply_markup
    if markup is None and with_controls:
        markup = get_voice_keyboard(slow=slow)

    cached_file_id = await sessions.get_tts_file_id(key)
    if cached_file_id:
        try:
            sent = await bot.send_voice(
                chat_id=chat_id, voice=cached_file_id, reply_markup=markup
            )
            await _remember(user_id, sent, phrase)
            return sent
        except TelegramBadRequest as e:
            logger.warning(f"Cached voice file_id rejected, re-synthesizing: {e}")
            await sessions.drop_tts_file_id(key)

    work_dir = tempfile.mkdtemp(prefix="tts_")
    stem = uuid.uuid4().hex[:8]
    wav_file = os.path.join(work_dir, f"{stem}.wav")
    ogg_file = os.path.join(work_dir, f"{stem}.ogg")
    try:
        await bot.send_chat_action(chat_id=chat_id, action="record_voice")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, ai.synthesize_speech, phrase, wav_file)
        await loop.run_in_executor(
            None, convert_wav_to_ogg_opus, wav_file, ogg_file, tempo
        )
        sent = await bot.send_voice(
            chat_id=chat_id, voice=FSInputFile(ogg_file), reply_markup=markup
        )
        if sent.voice:
            await sessions.set_tts_file_id(key, sent.voice.file_id)
        await _remember(user_id, sent, phrase)
        return sent
    except Exception:
        logger.exception(f"TTS failed for user {user_id}")
        return None
    finally:
        remove_files(wav_file, ogg_file)
        try:
            os.rmdir(work_dir)
        except OSError:
            pass

async def _remember(user_id: int, sent: Message, phrase: str) -> None:
    """Привязывает фразу к голосовому сообщению — для «ещё раз» и «медленнее»."""
    await sessions.set_speakable(user_id, sent.message_id, phrase)
