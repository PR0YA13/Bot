import requests
import time
from typing import Optional, Tuple, List, Dict
import logging
from urllib.parse import quote_plus
from config import APIFLASH_KEY, SHEET_URL, SCREENSHOT_WIDTH, SCREENSHOT_HEIGHT, SCREENSHOT_QUALITY
import json
from datetime import datetime, timedelta
import pytz
import os

# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('logs/telegram_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ScreenshotStats:
    def __init__(self):
        self.monthly_limit = 100

    def get_total_monthly_stats(self, screenshots: List[Dict]) -> Dict:
        """Get total statistics for all users and system screenshots in the current month"""
        now = datetime.now(pytz.UTC)
        current_month = now.strftime("%Y-%m")

        # Фильтруем все скриншоты (включая системные) за текущий месяц
        month_screenshots = [
            s for s in screenshots
            if s["timestamp"].startswith(current_month)
        ]

        total_monthly = len(month_screenshots)
        usage_percent = min(100, (total_monthly / self.monthly_limit) * 100)

        logger.info(f"Total screenshots this month: {total_monthly}")
        logger.info(f"Monthly limit: {self.monthly_limit}")
        logger.info(f"Usage percent: {usage_percent}%")

        return {
            "total_this_month": total_monthly,
            "remaining_limit": max(0, self.monthly_limit - total_monthly),
            "usage_percent": usage_percent
        }

    def get_monthly_stats(self, screenshots: List[Dict]) -> Dict:
        """Get statistics for specific user screenshots in the current month"""
        return self.get_total_monthly_stats(screenshots)

    def filter_by_period(self, screenshots: List[Dict], start_date: str, end_date: str) -> List[Dict]:
        """Filter screenshots by date period"""
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")

            return [
                s for s in screenshots
                if start <= datetime.strptime(s["timestamp"].split()[0], "%Y-%m-%d") <= end
            ]
        except Exception as e:
            logger.error(f"Error filtering screenshots by period: {e}")
            return []

screenshot_stats = ScreenshotStats()

class ScreenshotCache:
    def __init__(self):
        self.cache = {}
        self.last_modified_times = {}
        logger.info("Screenshot cache initialized")

    def _get_sheet_last_modified(self, url: str) -> Optional[str]:
        """
        Получает время последнего изменения Google таблицы
        """
        try:
            # Извлекаем ID таблицы из URL
            sheet_id = url.split('/d/')[1].split('/')[0]
            api_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/revisions/tiles"
            logger.info(f"Checking last modified time for sheet: {sheet_id}")

            response = requests.get(api_url)

            if response.status_code == 200:
                # Парсим время последнего изменения
                last_modified = response.headers.get('last-modified')
                logger.info(f"Sheet last modified time: {last_modified}")
                return last_modified

            logger.warning(f"Failed to get last modified time. Status code: {response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Error getting sheet last modified time: {str(e)}")
            return None

    def get(self, key: str) -> Optional[bytes]:
        """
        Получает скриншот из кэша, проверяя актуальность данных
        """
        logger.info(f"Attempting to get screenshot from cache for key: {key}")

        if key in self.cache:
            timestamp, data = self.cache[key]
            last_modified = self._get_sheet_last_modified(SHEET_URL)

            if last_modified and last_modified == self.last_modified_times.get(key):
                if time.time() - timestamp < 3600:  # 1 час кэша
                    logger.info(f"Cache hit for key: {key}")
                    return data

            logger.info(f"Cache expired or sheet modified for key: {key}")
            del self.cache[key]
            if key in self.last_modified_times:
                del self.last_modified_times[key]
                logger.info(f"Removed expired cache entry for key: {key}")
        else:
            logger.info(f"No cache entry found for key: {key}")
        return None

    def set(self, key: str, data: bytes) -> None:
        """
        Сохраняет скриншот в кэш вместе со временем последнего изменения таблицы
        """
        logger.info(f"Caching screenshot for key: {key}")
        last_modified = self._get_sheet_last_modified(SHEET_URL)
        if last_modified:
            self.last_modified_times[key] = last_modified
            logger.info(f"Updated last modified time for key: {key}")
        self.cache[key] = (time.time(), data)
        logger.info(f"Screenshot cached successfully for key: {key}")

screenshot_cache = ScreenshotCache()

def take_screenshot(url: str = SHEET_URL) -> bytes:
    """Take a screenshot of the specified URL using APIFlash"""
    try:
        params = {
            'access_key': APIFLASH_KEY,
            'url': url,
            'width': SCREENSHOT_WIDTH,
            'height': SCREENSHOT_HEIGHT,
            'quality': SCREENSHOT_QUALITY,
            'full_page': True,
            'response_type': 'json'
        }

        response = requests.get('https://api.apiflash.com/v1/urltoimage', params=params)
        response.raise_for_status()

        # Get the screenshot URL from the JSON response
        screenshot_url = response.json().get('url')
        if not screenshot_url:
            logger.error("No screenshot URL in response")
            return None

        # Download the actual screenshot
        screenshot_response = requests.get(screenshot_url)
        screenshot_response.raise_for_status()

        return screenshot_response.content

    except Exception as e:
        logger.error(f"Error taking screenshot: {e}")
        return None