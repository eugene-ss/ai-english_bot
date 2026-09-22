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

    def clear(self, user_id: int):
        if self.use_redis:
            try:
                key = f"chat_session:{user_id}"
                self.redis.delete(key)
                return
            except Exception as e:
                logger.error(f"Redis DELETE failed for user {user_id}: {e}")

        if user_id in self.local_storage:
            self.local_storage[user_id] = []

sessions = DurableStorage()
