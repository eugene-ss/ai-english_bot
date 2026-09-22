import json
import logging

from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from src.config import settings

logger = logging.getLogger("eng_bot")

class DurableStorage:
    def __init__(self):
        self.use_redis = settings.bot.use_redis
        self.local_storage = {}
        self.local_speakable = {}
        self.redis = None

        if self.use_redis:
            try:
                self.redis = Redis.from_url(
                    settings.redis_url.get_secret_value(),
                    decode_responses=True,
                    socket_connect_timeout=2.0,
                )
                self.redis.ping()
                logger.info("Successfully connected to Redis instance.")
            except (RedisConnectionError, Exception) as e:
                logger.warning(
                    f"Redis connection failed ({e}). "
                    f"Falling back to volatile In-Memory history storage."
                )
                self.use_redis = False

    def get_history(self, user_id: int) -> list:
        if self.use_redis:
            try:
                key = f"chat_session:{user_id}"
                data = self.redis.get(key)
                return json.loads(data) if data else []
            except Exception as e:
                logger.error(f"Redis GET failed for user {user_id}, running memory fallback: {e}")
                return self.local_storage.get(user_id, [])
        return self.local_storage.get(user_id, [])

    def add(self, user_id: int, role: str, text: str):
        history = self.get_history(user_id)
        history.append({"role": role, "text": text})

        if len(history) > settings.bot.max_history_len:
            history = history[-settings.bot.max_history_len:]

        if self.use_redis:
            try:
                key = f"chat_session:{user_id}"
                self.redis.set(key, json.dumps(history), ex=172800)
                return
            except Exception as e:
                logger.error(f"Redis SET failed for user {user_id}, running memory fallback: {e}")

        self.local_storage[user_id] = history

    def set_last_speakable(self, user_id: int, text: str) -> None:
        self.local_speakable[user_id] = text
        if self.use_redis:
            try:
                self.redis.set(f"speakable:{user_id}", text, ex=172800)
            except Exception as e:
                logger.error(f"Redis SET speakable failed for user {user_id}: {e}")

    def get_last_speakable(self, user_id: int) -> str:
        if self.use_redis:
            try:
                value = self.redis.get(f"speakable:{user_id}")
                if value:
                    return value
            except Exception as e:
                logger.error(f"Redis GET speakable failed for user {user_id}: {e}")
        return self.local_speakable.get(user_id, "")

    def clear(self, user_id: int):
        self.local_storage[user_id] = []
        self.local_speakable.pop(user_id, None)
        if self.use_redis:
            try:
                pipe = self.redis.pipeline()
                pipe.delete(f"chat_session:{user_id}")
                pipe.delete(f"speakable:{user_id}")
                pipe.execute()
            except Exception as e:
                logger.error(f"Redis DELETE failed for user {user_id}: {e}")

sessions = DurableStorage()
