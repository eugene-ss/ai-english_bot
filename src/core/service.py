import asyncio
import time
from dataclasses import dataclass

from src.config import settings
from src.core.llm import LLMUnavailableError, ai
from src.core.sessions import sessions
from src.locale import t
from src.util.speakable import extract_speakable_english, strip_say_tag


class BusyError(RuntimeError):
    """Для пользователя уже выполняется запрос."""


class ThrottledError(RuntimeError):
    """Запросы идут слишком часто."""


class NothingToExplainError(RuntimeError):
    """Нет реплики учителя, которую можно разобрать."""


@dataclass(frozen=True)
class LessonReply:
    """Ответ учителя: текст для чата и короткая фраза для озвучки."""

    text: str
    speakable: str


class TutorService:
    """Сценарий урока. Хендлеры Telegram только вызывают эти методы."""

    def __init__(self):
        self._locks: dict[int, asyncio.Lock] = {}
        self._last_request_at: dict[int, float] = {}

    def _lock_for(self, user_id: int) -> asyncio.Lock:
        lock = self._locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[user_id] = lock
        return lock

    def _check_rate(self, user_id: int) -> None:
        now = time.monotonic()
        last = self._last_request_at.get(user_id, 0.0)
        if now - last < settings.bot.min_request_interval_s:
            raise ThrottledError
        self._last_request_at[user_id] = now

    def _release_locks(self, user_id: int) -> None:
        lock = self._locks.get(user_id)
        if lock is not None and not lock.locked():
            self._locks.pop(user_id, None)

    async def _ask(
        self,
        user_id: int,
        *,
        persist_user_text: str | None,
        ephemeral_instruction: str | None,
        persist_answer: bool,
    ) -> LessonReply:
        """Единый путь запроса к модели.

        Служебные инструкции передаются модели, но в историю не попадают:
        иначе она позже начинает их комментировать. Ответ дописывается только
        если контекст не сбрасывали во время запроса.
        """
        if persist_user_text:
            await sessions.add(user_id, "user", persist_user_text)

        generation = await sessions.get_generation(user_id)
        history = await sessions.get_history(user_id)
        if ephemeral_instruction:
            history = history + [{"role": "user", "text": ephemeral_instruction}]

        raw_answer = await ai.get_text_response(history)

        if persist_answer:
            await sessions.add_if_current(user_id, "assistant", raw_answer, generation)

        visible = strip_say_tag(raw_answer)
        speakable = (
            extract_speakable_english(raw_answer, max_chars=settings.tts.max_chars)
            if ai.tts_available
            else ""
        )
        return LessonReply(text=visible or raw_answer, speakable=speakable)

    async def _guarded(self, user_id: int, coro_factory):
        self._check_rate(user_id)
        lock = self._lock_for(user_id)
        if lock.locked():
            raise BusyError
        async with lock:
            try:
                return await coro_factory()
            finally:
                self._release_locks(user_id)

    # --- публичные сценарии ----------------------------------------------

    async def reply_to_text(self, user_id: int, user_text: str) -> LessonReply:
        return await self._guarded(
            user_id,
            lambda: self._ask(
                user_id,
                persist_user_text=user_text,
                ephemeral_instruction=None,
                persist_answer=True,
            ),
        )

    async def reply_to_voice(self, user_id: int, transcript: str) -> LessonReply:
        return await self._guarded(
            user_id,
            lambda: self._ask(
                user_id,
                persist_user_text=transcript,
                ephemeral_instruction=t("instruction_voice_turn"),
                persist_answer=True,
            ),
        )

    async def explain_last(self, user_id: int) -> LessonReply:
        last_assistant = await sessions.get_last_assistant(user_id)
        if not last_assistant.strip():
            raise NothingToExplainError

        return await self._guarded(
            user_id,
            lambda: self._ask(
                user_id,
                persist_user_text=None,
                # Текст передаём явно: без якоря модель разбирает системный промпт
                ephemeral_instruction=t(
                    "prompt_explain", text=strip_say_tag(last_assistant)
                ),
                # Разбор грамматики — сноска, в поток урока её не пишем
                persist_answer=False,
            ),
        )

    async def next_question(self, user_id: int) -> LessonReply:
        return await self._guarded(
            user_id,
            lambda: self._ask(
                user_id,
                persist_user_text=None,
                ephemeral_instruction=t("prompt_next_question"),
                persist_answer=True,
            ),
        )

    async def reset(self, user_id: int) -> None:
        await sessions.clear(user_id)
        self._last_request_at.pop(user_id, None)


tutor = TutorService()

__all__ = [
    "BusyError",
    "LLMUnavailableError",
    "LessonReply",
    "NothingToExplainError",
    "ThrottledError",
    "TutorService",
    "tutor",
]
