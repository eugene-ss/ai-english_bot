import asyncio

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from redis.exceptions import RedisError

from src.config import settings
from src.core import sessions
from src.ui import dialog_handlers, handlers
from src.util.logging import setup_logging

logger = setup_logging()

async def build_storage() -> BaseStorage:
    """Состояния сценариев переживают перезапуск, если доступен Redis."""
    if not settings.bot.use_redis:
        return MemoryStorage()
    try:
        storage = RedisStorage.from_url(settings.redis_url.get_secret_value())
        await storage.redis.ping()
        logger.info("FSM state is backed by Redis.")
        return storage
    except (RedisError, OSError) as e:
        logger.warning(f"Redis unavailable for FSM ({e}), falling back to memory.")
        return MemoryStorage()

def build_bot() -> Bot:
    return Bot(token=settings.telegram_bot_token.get_secret_value())

def build_dispatcher(storage: BaseStorage) -> Dispatcher:
    dp = Dispatcher(storage=storage)
    # Диалог идёт первым: внутри сценария он забирает апдейты по состоянию
    dp.include_router(dialog_handlers.router)
    dp.include_router(handlers.router)
    return dp

async def main():
    logger.info("Initializing Application Service Engine under active configuration profiles...")
    bot = build_bot()
    storage = await build_storage()
    dp = build_dispatcher(storage)

    try:
        # Отбрасываем накопившиеся обновления, чтобы после простоя бот не
        # отвечал на устаревшие сообщения
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await storage.close()
        await sessions.close()
        await bot.session.close()
        logger.info("Shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Interrupted by signal.")
