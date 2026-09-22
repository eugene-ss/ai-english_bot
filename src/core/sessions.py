import json
import logging
import time

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from src.config import settings

logger = logging.getLogger("eng_bot")

# Дописываем сообщение только если поколение сессии не изменилось: сброс
# контекста во время ожидания ответа LLM инкрементит поколение, и запоздавший
# ответ отбрасывается вместо оживления очищенной истории.
_APPEND_IF_CURRENT_LUA = """
local expected = ARGV[1]
local current = redis.call('GET', KEYS[2])
if current == false then current = '0' end
if current ~= expected then return 0 end
redis.call('RPUSH', KEYS[1], ARGV[2])
redis.call('LTRIM', KEYS[1], -tonumber(ARGV[3]), -1)
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[4]))
return 1
"""


class DurableStorage:
    """История диалога: Redis-список либо память как фолбэк.

    Все операции записи атомарны, поэтому одновременные сообщения одного
    пользователя не перетирают друг друга.
    """

    def __init__(self):
        self._redis: aioredis.Redis | None = None
        self._append_script = None
        self._redis_ready = False
        self._next_retry_at = 0.0
        self._local_history: dict[int, list[dict]] = {}
        self._local_generation: dict[int, int] = {}
        self._local_speakable: dict[tuple[int, int], str] = {}

    # --- подключение -----------------------------------------------------

    async def _ensure_redis(self) -> aioredis.Redis | None:
        if not settings.bot.use_redis:
            return None
        if self._redis_ready and self._redis is not None:
            return self._redis
        if time.monotonic() < self._next_retry_at:
            return None

        try:
            if self._redis is None:
                self._redis = aioredis.Redis.from_url(
                    settings.redis_url.get_secret_value(),
                    decode_responses=True,
                    socket_connect_timeout=2.0,
                    socket_timeout=2.0,
                )
                self._append_script = self._redis.register_script(_APPEND_IF_CURRENT_LUA)
            await self._redis.ping()
            if not self._redis_ready:
                logger.info("Connected to Redis instance.")
            self._redis_ready = True
            return self._redis
        except (RedisError, OSError) as e:
            self._redis_ready = False
            self._next_retry_at = time.monotonic() + settings.bot.redis_retry_interval_s
            logger.warning(
                f"Redis unavailable ({e}). Using in-memory history, "
                f"retry in {settings.bot.redis_retry_interval_s:g}s."
            )
            return None

    def _drop_redis(self, error: Exception, op: str) -> None:
        self._redis_ready = False
        self._next_retry_at = time.monotonic() + settings.bot.redis_retry_interval_s
        logger.error(f"Redis {op} failed, falling back to memory: {error}")

    async def close(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception as e:
                logger.warning(f"Redis close failed: {e}")
            finally:
                self._redis = None
                self._redis_ready = False

    # --- история ---------------------------------------------------------

    @staticmethod
    def _history_key(user_id: int) -> str:
        return f"chat_session:{user_id}"

    @staticmethod
    def _generation_key(user_id: int) -> str:
        return f"chat_generation:{user_id}"

    async def get_generation(self, user_id: int) -> int:
        client = await self._ensure_redis()
        if client is not None:
            try:
                raw = await client.get(self._generation_key(user_id))
                return int(raw) if raw else 0
            except (RedisError, OSError, ValueError) as e:
                self._drop_redis(e, "GET generation")
        return self._local_generation.get(user_id, 0)

    async def get_history(self, user_id: int) -> list[dict]:
        client = await self._ensure_redis()
        if client is not None:
            try:
                raw_items = await client.lrange(self._history_key(user_id), 0, -1)
                return [json.loads(item) for item in raw_items]
            except (RedisError, OSError, json.JSONDecodeError) as e:
                self._drop_redis(e, "LRANGE")
        return list(self._local_history.get(user_id, []))

    async def add(self, user_id: int, role: str, text: str) -> bool:
        generation = await self.get_generation(user_id)
        return await self.add_if_current(user_id, role, text, generation)

    async def add_if_current(
        self, user_id: int, role: str, text: str, generation: int
    ) -> bool:
        """Дописывает сообщение, если сессия не сбрасывалась. False — отброшено."""
        payload = json.dumps({"role": role, "text": text}, ensure_ascii=False)
        max_len = settings.bot.max_history_len
        ttl = settings.bot.session_ttl_s

        client = await self._ensure_redis()
        if client is not None and self._append_script is not None:
            try:
                written = await self._append_script(
                    keys=[self._history_key(user_id), self._generation_key(user_id)],
                    args=[str(generation), payload, str(max_len), str(ttl)],
                )
                return bool(int(written))
            except (RedisError, OSError) as e:
                self._drop_redis(e, "append script")

        if self._local_generation.get(user_id, 0) != generation:
            return False
        history = self._local_history.setdefault(user_id, [])
        history.append({"role": role, "text": text})
        if len(history) > max_len:
            del history[:-max_len]
        return True

    async def get_last_assistant(self, user_id: int) -> str:
        for message in reversed(await self.get_history(user_id)):
            if message.get("role") == "assistant":
                return message.get("text", "")
        return ""

    async def clear(self, user_id: int) -> None:
        self._local_history[user_id] = []
        self._local_generation[user_id] = self._local_generation.get(user_id, 0) + 1
        self._local_speakable = {
            key: value for key, value in self._local_speakable.items() if key[0] != user_id
        }

        client = await self._ensure_redis()
        if client is not None:
            try:
                index_key = self._speakable_index_key(user_id)
                message_ids = await client.smembers(index_key)
                pipe = client.pipeline()
                pipe.incr(self._generation_key(user_id))
                pipe.expire(self._generation_key(user_id), settings.bot.session_ttl_s)
                pipe.delete(self._history_key(user_id), index_key)
                for message_id in message_ids:
                    pipe.delete(self._speakable_key(user_id, message_id))
                await pipe.execute()
            except (RedisError, OSError) as e:
                self._drop_redis(e, "clear")

    # --- фраза для озвучки ------------------------------------------------

    @staticmethod
    def _speakable_key(user_id: int, message_id: int | str) -> str:
        return f"speakable:{user_id}:{message_id}"

    @staticmethod
    def _speakable_index_key(user_id: int) -> str:
        return f"speakable_index:{user_id}"

    async def set_speakable(self, user_id: int, message_id: int, text: str) -> None:
        """Фраза привязана к сообщению: кнопка под старым ответом озвучит именно его.

        Идентификаторы складываются в индекс, иначе после сброса контекста
        кнопка под старым сообщением продолжала бы озвучивать удалённую сессию.
        """
        self._local_speakable[(user_id, message_id)] = text
        client = await self._ensure_redis()
        if client is not None:
            try:
                ttl = settings.bot.session_ttl_s
                index_key = self._speakable_index_key(user_id)
                pipe = client.pipeline()
                pipe.set(self._speakable_key(user_id, message_id), text, ex=ttl)
                pipe.sadd(index_key, message_id)
                pipe.expire(index_key, ttl)
                await pipe.execute()
            except (RedisError, OSError) as e:
                self._drop_redis(e, "SET speakable")

    async def get_speakable(self, user_id: int, message_id: int) -> str:
        client = await self._ensure_redis()
        if client is not None:
            try:
                value = await client.get(self._speakable_key(user_id, message_id))
                if value:
                    return value
            except (RedisError, OSError) as e:
                self._drop_redis(e, "GET speakable")
        return self._local_speakable.get((user_id, message_id), "")


sessions = DurableStorage()
