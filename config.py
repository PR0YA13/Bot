import os
import logging

logger = logging.getLogger(__name__)

# Configuration settings for the bot
TELEGRAM_TOKEN = "7828274961:AAGKNxMciaRR7lfgWWERw6kWKreCintykq0"
APIFLASH_KEY = "be63628b371a4dd38a26f16545f01071"
SHEET_URL = "https://docs.google.com/spreadsheets/d/1o_RhLTXTC2D-W55sBvbftUnyJDv8z4OnbXoP-4tr_04/edit?gid=2045841507#gid=2045841507"

# Validate configuration
if not APIFLASH_KEY:
    logger.error("APIFlash key is not set!")
if not SHEET_URL:
    logger.error("Google Sheet URL is not set!")

# APIFlash screenshot settings
SCREENSHOT_WIDTH = 2440
SCREENSHOT_HEIGHT = 2000
SCREENSHOT_QUALITY = 100

# Cache settings
CACHE_DURATION = 3600  # 1 hour in seconds

# Supported image formats
SUPPORTED_FORMATS = ['PNG', 'JPEG', 'WEBP']