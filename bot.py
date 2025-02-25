import asyncio
import logging
from aiogram import Bot, Dispatcher
from handlers import register_handlers
from config import TELEGRAM_TOKEN
import os

# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/telegram_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

from scheduler import scheduler

async def main():
    """Main function to start the bot."""
    bot = None
    dp = None

    try:
        logger.info("Starting bot initialization process...")

        # Initialize Bot instance with token
        bot = Bot(token=TELEGRAM_TOKEN)
        logger.info("Bot instance created")

        # Create new dispatcher
        dp = Dispatcher()
        logger.info("Dispatcher created")

        # Start scheduler in background
        logger.info("Starting scheduler...")
        scheduler_task = asyncio.create_task(scheduler())
        logger.info("Scheduler task created")

        # Delete webhook and drop pending updates
        logger.info("Cleaning up previous bot state...")
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Previous bot state cleaned")

        # Register all handlers
        register_handlers(dp)
        logger.info("Handlers registered successfully")

        # Start polling
        logger.info("Starting polling...")
        await dp.start_polling(bot, allowed_updates=['message', 'callback_query'])

    except Exception as e:
        logger.error(f"Critical error during bot startup: {e}", exc_info=True)
        raise
    finally:
        # Shutdown
        if bot:
            logger.info("Closing bot session...")
            await bot.session.close()
            logger.info("Bot session closed")
        if dp:
            logger.info("Closing dispatcher...")
            await dp.storage.close()
            logger.info("Dispatcher storage closed")

if __name__ == '__main__':
    try:
        logger.info("Starting bot main process...")
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot stopped due to error: {e}", exc_info=True)
