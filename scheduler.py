import asyncio
import aioschedule
import pytz
from datetime import datetime, timedelta
from utils import take_screenshot
from config import SHEET_URL
from storage import ScreenshotStorage
from typing import Optional
import logging

logger = logging.getLogger(__name__)

screenshot_storage = ScreenshotStorage()

async def take_scheduled_screenshot(label: str = None) -> None:
    """Take a screenshot and save it with a label"""
    try:
        if not label:
            logger.warning("No label provided for scheduled screenshot")
            return

        logger.info(f"Starting scheduled screenshot with label: {label}")
        screenshot_data = take_screenshot(SHEET_URL)

        if screenshot_data:
            # Используем system user ID и chat ID для автоматических скриншотов
            system_user_id = 0
            system_chat_id = 0

            logger.info(f"Saving scheduled screenshot with label: {label}")
            filepath = screenshot_storage.save_screenshot(
                screenshot_data, 
                label, 
                system_user_id, 
                system_chat_id
            )

            if filepath:
                logger.info(f"Successfully saved scheduled screenshot to: {filepath}")
            else:
                logger.error("Failed to save scheduled screenshot")
        else:
            logger.error("Failed to take scheduled screenshot - no data received")

    except Exception as e:
        logger.error(f"Error taking scheduled screenshot: {e}")

async def check_and_take_screenshot() -> None:
    """Check current date and take screenshot with appropriate label"""
    try:
        now = datetime.now(pytz.UTC)
        logger.info(f"Running scheduled check at: {now}")

        # Проверяем, был ли уже сделан скриншот сегодня
        today_label = f"Ежедневный отчет {now.strftime('%Y-%m-%d')}"
        today_screenshots = screenshot_storage.get_screenshots_by_label(today_label, 0, 0)

        if today_screenshots:
            logger.info(f"Daily screenshot already exists for {now.strftime('%Y-%m-%d')}")
            return

        # Определяем последний день месяца
        next_month = now.replace(day=28) + timedelta(days=4)
        last_day = next_month - timedelta(days=next_month.day)

        # Создаем метки в зависимости от дня месяца
        if now.day == 1:
            logger.info("Taking start of month screenshot")
            await take_scheduled_screenshot(f"Начало месяца {now.strftime('%Y-%m-%d')}")
        elif now.day == 15:
            logger.info("Taking mid-month screenshot")
            await take_scheduled_screenshot(f"Середина месяца {now.strftime('%Y-%m-%d')}")
        elif now.day == last_day.day:
            logger.info("Taking end of month screenshot")
            await take_scheduled_screenshot(f"Конец месяца {now.strftime('%Y-%m-%d')}")

        # Ежедневный скриншот
        logger.info("Taking daily screenshot")
        await take_scheduled_screenshot(today_label)

    except Exception as e:
        logger.error(f"Error in check_and_take_screenshot: {e}")

async def scheduler() -> None:
    """Setup and run the scheduler"""
    try:
        logger.info("Starting scheduler...")

        # Планируем ежедневную проверку в полночь
        aioschedule.every().day.at("00:01").do(check_and_take_screenshot)
        logger.info("Scheduled daily check for 00:01")

        # Планируем ежедневный скриншот в 23:00
        aioschedule.every().day.at("23:00").do(
            take_scheduled_screenshot,
            f"Ежедневный отчет {datetime.now(pytz.UTC).strftime('%Y-%m-%d')}"
        )
        logger.info("Scheduled daily screenshot for 23:00")

        logger.info("Scheduler started successfully")

        while True:
            await aioschedule.run_pending()
            await asyncio.sleep(60)

    except Exception as e:
        logger.error(f"Error in scheduler: {e}")
        # Пытаемся перезапустить scheduler после ошибки
        logger.info("Attempting to restart scheduler in 60 seconds...")
        await asyncio.sleep(60)
        await scheduler()