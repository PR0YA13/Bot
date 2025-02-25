import os
import json
from datetime import datetime
import pytz
import logging
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)

class ScreenshotStorage:
    def __init__(self):
        self.storage_dir = "screenshots"
        self.metadata_file = os.path.join(self.storage_dir, "metadata.json")
        self._ensure_storage_exists()
        self.metadata = self._load_metadata()

    def _ensure_storage_exists(self):
        """Create storage directory if it doesn't exist"""
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)
            logger.info(f"Created storage directory: {self.storage_dir}")

    def _load_metadata(self) -> Dict:
        """Load metadata from file"""
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading metadata: {e}")
                return {}
        return {}

    def _save_metadata(self):
        """Save metadata to file"""
        try:
            with open(self.metadata_file, 'w') as f:
                json.dump(self.metadata, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving metadata: {e}")

    def _get_user_dir(self, user_id: int, chat_id: int) -> str:
        """Get directory for specific user and chat"""
        dir_path = os.path.join(self.storage_dir, f"user_{user_id}", f"chat_{chat_id}")
        os.makedirs(dir_path, exist_ok=True)
        return dir_path

    def _has_access(self, user_id: int, chat_id: int, screenshot_info: Dict) -> bool:
        """Check if user has access to the screenshot"""
        # Отключаем проверку прав доступа
        return True

    def delete_screenshot(self, filename: str, user_id: int, chat_id: int) -> bool:
        """Delete screenshot and its metadata for specific user and chat"""
        try:
            user_key = f"user_{user_id}_chat_{chat_id}"
            system_key = "user_0_chat_0"  # Системные скриншоты

            logger.info(f"[DELETE] Starting deletion process for file {filename}")
            logger.info(f"[DELETE] Current metadata keys: {list(self.metadata.keys())}")

            # Remove 'category_' prefix if it exists
            if filename.startswith('category_'):
                filename = filename.replace('category_', '')
                logger.info(f"[DELETE] Removed category_ prefix, new filename: {filename}")

            # Проверяем в пользовательских скриншотах
            screenshot_info = None
            is_system = False

            # Сначала ищем в пользовательских скриншотах
            if user_key in self.metadata:
                for info in self.metadata[user_key]:
                    current_filename = os.path.basename(info["filepath"])
                    logger.info(f"[DELETE] Comparing {current_filename} with {filename}")
                    if current_filename == filename:
                        screenshot_info = info
                        logger.info(f"[DELETE] Found screenshot in user storage: {filename}")
                        break

            # Если не нашли в пользовательских, ищем в системных
            if not screenshot_info and system_key in self.metadata:
                for info in self.metadata[system_key]:
                    current_filename = os.path.basename(info["filepath"])
                    logger.info(f"[DELETE] Comparing {current_filename} with {filename} in system storage")
                    if current_filename == filename:
                        screenshot_info = info
                        is_system = True
                        logger.info(f"[DELETE] Found screenshot in system storage: {filename}")
                        break

            if screenshot_info:
                filepath = screenshot_info["filepath"]
                logger.info(f"[DELETE] Found screenshot info: {screenshot_info}")

                # Проверяем существование файла
                if not os.path.exists(filepath):
                    logger.warning(f"[DELETE] File not found on disk: {filepath}")
                    # Удаляем только метаданные, если файл не существует
                    if is_system:
                        self.metadata[system_key].remove(screenshot_info)
                    else:
                        self.metadata[user_key].remove(screenshot_info)
                    self._save_metadata()
                    return True

                try:
                    # Удаляем файл
                    os.remove(filepath)
                    logger.info(f"[DELETE] Successfully deleted file: {filepath}")
                except Exception as e:
                    logger.error(f"[DELETE] Error deleting file {filepath}: {e}")
                    return False

                # Удаляем метаданные
                try:
                    if is_system:
                        self.metadata[system_key].remove(screenshot_info)
                    else:
                        self.metadata[user_key].remove(screenshot_info)
                    self._save_metadata()
                    logger.info(f"[DELETE] Successfully deleted metadata for: {filename}")
                    return True
                except Exception as e:
                    logger.error(f"[DELETE] Error deleting metadata for {filename}: {e}")
                    return False
            else:
                logger.error(f"[DELETE] Screenshot info not found for file: {filename}")
                logger.info(f"[DELETE] Available metadata: {self.metadata}")
                return False

        except Exception as e:
            logger.error(f"[DELETE] Error in delete_screenshot: {e}", exc_info=True)
            return False

    def get_screenshots_by_label(self, label: str, user_id: int, chat_id: int) -> List[Dict]:
        """Get all screenshots with specific label for user and chat"""
        try:
            user_key = f"user_{user_id}_chat_{chat_id}"
            system_key = "user_0_chat_0"  # Системные скриншоты

            # Remove 'category_' prefix if it exists
            if label.startswith('category_'):
                label = label.replace('category_', '')
                logger.info(f"[GET_BY_LABEL] Removed category_ prefix, new label: {label}")

            logger.info(f"[GET_BY_LABEL] Searching for label: {label}")
            logger.info(f"[GET_BY_LABEL] User key: {user_key}")
            logger.info(f"[GET_BY_LABEL] System key: {system_key}")

            # Нормализуем метку для сравнения
            normalized_label = label.strip().lower().replace('ё', 'е')
            logger.info(f"[GET_BY_LABEL] Normalized label: {normalized_label}")

            # Получаем пользовательские скриншоты с данной меткой
            user_screenshots = [
                info for info in self.metadata.get(user_key, [])
                if info["label"].strip().lower().replace('ё', 'е') == normalized_label
            ]
            logger.info(f"[GET_BY_LABEL] Found {len(user_screenshots)} user screenshots")

            # Получаем системные скриншоты с данной меткой
            system_screenshots = [
                info for info in self.metadata.get(system_key, [])
                if info["label"].strip().lower().replace('ё', 'е') == normalized_label
            ]
            logger.info(f"[GET_BY_LABEL] Found {len(system_screenshots)} system screenshots")

            # Объединяем списки
            all_screenshots = user_screenshots + system_screenshots

            logger.info(f"[GET_BY_LABEL] Total screenshots found: {len(all_screenshots)}")
            if all_screenshots:
                logger.info("Found screenshots:")
                for screenshot in all_screenshots:
                    logger.info(f"[GET_BY_LABEL] - {os.path.basename(screenshot['filepath'])}, Label: {screenshot['label']}")
            else:
                logger.warning(f"[GET_BY_LABEL] No screenshots found with label '{label}'")

            return sorted(all_screenshots, key=lambda x: x["timestamp"], reverse=True)

        except Exception as e:
            logger.error(f"[GET_BY_LABEL] Error getting screenshots by label: {e}", exc_info=True)
            return []

    def get_all_screenshots(self, user_id: int, chat_id: int) -> List[Dict]:
        """Get all screenshots metadata for specific user and chat"""
        user_key = f"user_{user_id}_chat_{chat_id}"
        system_key = "user_0_chat_0"  # Системные скриншоты

        # Получаем пользовательские скриншоты
        user_screenshots = self.metadata.get(user_key, [])

        # Если это не системный пользователь, добавляем системные скриншоты
        if user_id != 0 or chat_id != 0:
            system_screenshots = self.metadata.get(system_key, [])
            # Объединяем списки
            all_screenshots = user_screenshots + system_screenshots
        else:
            all_screenshots = user_screenshots

        return sorted(
            all_screenshots,
            key=lambda x: x["timestamp"],
            reverse=True
        )

    def save_screenshot(self, data: bytes, label: str, user_id: int, chat_id: int) -> str:
        """Save screenshot with metadata for specific user and chat"""
        timestamp = datetime.now(pytz.UTC).strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}.png"

        # Get user-specific directory
        user_dir = self._get_user_dir(user_id, chat_id)
        filepath = os.path.join(user_dir, filename)

        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            with open(filepath, 'wb') as f:
                f.write(data)

            # Create or update user metadata
            user_key = f"user_{user_id}_chat_{chat_id}"
            if user_key not in self.metadata:
                self.metadata[user_key] = []

            screenshot_info = {
                "label": label,
                "timestamp": timestamp,
                "filepath": filepath,
                "user_id": user_id,
                "chat_id": chat_id
            }

            self.metadata[user_key].append(screenshot_info)
            self._save_metadata()

            logger.info(f"Saved screenshot: {filename} with label: {label} for user {user_id} in chat {chat_id}")
            return filepath
        except Exception as e:
            logger.error(f"Error saving screenshot: {e}")
            return None

    def get_screenshots_by_date(self, date: str, user_id: int, chat_id: int) -> List[Dict]:
        """Get screenshots for specific date for user and chat"""
        user_key = f"user_{user_id}_chat_{chat_id}"
        system_key = "user_0_chat_0"  # Системные скриншоты

        # Получаем пользовательские скриншоты за указанную дату
        user_screenshots = [
            info for info in self.metadata.get(user_key, [])
            if info["timestamp"].startswith(date) and self._has_access(user_id, chat_id, info)
        ]

        # Если это не системный пользователь, добавляем системные скриншоты
        if user_id != 0 or chat_id != 0:
            system_screenshots = [
                info for info in self.metadata.get(system_key, [])
                if info["timestamp"].startswith(date) and self._has_access(user_id, chat_id, info)
            ]
            # Объединяем списки
            all_screenshots = user_screenshots + system_screenshots
        else:
            all_screenshots = user_screenshots

        return sorted(all_screenshots, key=lambda x: x["timestamp"], reverse=True)

    def search_by_label(self, query: str, user_id: int, chat_id: int) -> List[Dict]:
        """Search screenshots by custom label for user and chat"""
        user_key = f"user_{user_id}_chat_{chat_id}"
        query = query.lower()
        return [
            info for info in self.metadata.get(user_key, [])
            if query in info["label"].lower() and self._has_access(user_id, chat_id, info)
        ]

    def get_all_labels(self, user_id: int, chat_id: int) -> List[str]:
        """Get all unique labels for user and chat"""
        user_key = f"user_{user_id}_chat_{chat_id}"
        system_key = "user_0_chat_0"  # Системные скриншоты

        labels = set()
        # Добавляем метки пользовательских скриншотов
        for info in self.metadata.get(user_key, []):
            if self._has_access(user_id, chat_id, info):
                labels.add(info["label"])

        # Если это не системный пользователь, добавляем метки системных скриншотов
        if user_id != 0 or chat_id != 0:
            for info in self.metadata.get(system_key, []):
                if self._has_access(user_id, chat_id, info):
                    labels.add(info["label"])

        return sorted(list(labels))

screenshot_storage = ScreenshotStorage()