import asyncio

from aiogram import Bot, Dispatcher

from src.config import settings
from src.core import sessions
from src.ui.handlers import router
from src.util.logging import setup_logging

logger = setup_logging()

def build_bot() -> Bot:
    return Bot(token=settings.telegram_bot_token.get_secret_value())

def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp

async def main():
    logger.info("Initializing Application Service Engine under active configuration profiles...")
    bot = build_bot()
    dp = build_dispatcher()

    try:
        # Отбрасываем накопившиеся обновления, чтобы после простоя бот не
        # отвечал на устаревшие сообщения
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await sessions.close()
        await bot.session.close()
        logger.info("Shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Interrupted by signal.")
