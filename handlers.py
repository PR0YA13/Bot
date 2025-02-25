import logging
import asyncio
import os
import tempfile
from datetime import datetime, timedelta
from typing import List, Dict, Set
from collections import defaultdict
import pytz

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram import types, Dispatcher

from storage import ScreenshotStorage
from config import SHEET_URL
from utils import take_screenshot, screenshot_stats
from image_processor import ImageProcessor

# Initialize storage and state variables
screenshot_storage = ScreenshotStorage()
temp_files: Dict[str, str] = {}  # Map of file_id to filepath
selected_screenshots: Dict[str, Set[str]] = defaultdict(set)  # Map of user_key to set of selected filenames

# Configure logging
logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

def log_action(action: str, details: str = None):
    """Расширенное логирование действий"""
    log_message = f"Action: {action}"
    if details:
        log_message += f" | Details: {details}"
    logger.info(log_message)

router = Router()

def register_handlers(dp: Dispatcher):
    """Register all handlers"""
    try:
        dp.include_router(router)
        logger.info("All handlers registered successfully")
    except Exception as e:
        logger.error(f"Error registering handlers: {e}", exc_info=True)
        raise

async def animated_progress_bar(message: Message, total_steps: int = 5) -> None:
    """
    Создает анимированный прогресс-бар с меньшим количеством эмодзи
    """
    progress_symbols = ["⬜️"] * total_steps
    loading_emojis = ["⏳", "⌛️"]  # Уменьшили количество эмодзи

    for step in range(total_steps + 1):
        for emoji in loading_emojis:
            progress_symbols[min(step, total_steps - 1)] = emoji
            progress_text = " ".join(progress_symbols)
            await message.edit_text(f"Обработка: {progress_text}")
            await asyncio.sleep(0.5)  # Увеличили интервал между анимациями

    # Заполняем все ячейки по завершении
    progress_symbols = ["✅"] * total_steps
    await message.edit_text(f"Готово! {' '.join(progress_symbols)}")

def create_animated_button(text: str, callback_data: str) -> InlineKeyboardButton:
    """
    Создает кнопку с анимированным текстом (эмодзи)
    """
    animated_buttons = {
        "take_screenshot": "📸 Сделать скриншот",
        "presets_menu": "⚙️ Пресеты",
        "help_menu": "❓ Помощь",
        "about": "ℹ️ О боте",
        "back_to_main": "◀️ Назад"
    }
    return InlineKeyboardButton(
        text=animated_buttons.get(callback_data, text),
        callback_data=callback_data
    )

@router.message(Command("start"))
async def handle_start(message: Message):
    """Start message handling"""
    try:
        logger.info(f"User {message.from_user.id} started the bot")
        await show_main_menu(message)
    except Exception as e:
        logger.error(f"Error in start handler: {e}")
        await message.answer("Произошла ошибка при запуске бота. Пожалуйста, попробуйте позже.")

async def show_main_menu(message: Message):
    """Show main menu with animated buttons"""
    keyboard = [
        [
            create_animated_button("📸 Сделать скриншот", "take_screenshot"),
            create_animated_button("⚙️ Пресеты", "presets_menu")
        ],
        [
            create_animated_button("📂 Архив", "view_archive")
        ],
        [
            create_animated_button("❓ Помощь", "help_menu"),
            create_animated_button("ℹ️ О боте", "about")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    # Определяем тип чата
    is_group = message.chat.type in ['group', 'supergroup']

    # Получаем общую статистику скриншотов
    all_screenshots = screenshot_storage.get_all_screenshots(0, 0)  # system user для автоматических скриншотов
    monthly_stats = screenshot_stats.get_total_monthly_stats(all_screenshots)

    welcome_text = (
        f"{'Привет всем' if is_group else f'Привет, {message.from_user.first_name}'}\n\n"
        "Я - бот для создания скриншотов Google таблиц.\n\n"
        "📊 Статистика за месяц:\n"
        f"• Создано скриншотов: {monthly_stats['total_this_month']}\n"
        f"• Осталось: {monthly_stats['remaining_limit']} из 100\n"
        f"• Использовано: {monthly_stats['usage_percent']:.1f}%\n\n"
        "Возможности:\n"
        "• Создание качественных скриншотов\n"
        "• Улучшение изображений с разными пресетами:\n"
        "  - Высокая контрастность\n"
        "  - Яркое изображение\n"
        "  - Чёткость\n"
        "  - Сбалансированный режим\n\n"
        "Выберите действие в меню ниже:"
    )

    await message.answer(welcome_text, reply_markup=reply_markup)
    logger.info("Main menu sent successfully")

@router.message(F.text == "📸 Сделать скриншот")
async def handle_screenshot_request(message: Message):
    """Handle screenshot button press"""
    try:
        logger.info("Creating screenshot menu")
        keyboard = [
            [
                InlineKeyboardButton(
                    text="✨ С улучшением",
                    callback_data='enhancement_menu'
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data='back_to_main'
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

        await message.answer(
            "Создаю обычный скриншот. Или выберите вариант с улучшением:",
            reply_markup=reply_markup
        )
        # Сразу начинаем создание обычного скриншота
        await handle_screenshot(message)
    except Exception as e:
        logger.error(f"Error in screenshot request handler: {e}")
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

# Обновляем обработчик меню пресетов с логированием
async def handle_presets_menu(message: Message):
    """Show presets menu without previews"""
    log_action("presets_menu_start", "Starting presets menu creation")

    keyboard = [
        [create_animated_button("Без улучшений", "preset_none")],
        [create_animated_button("Высокая контрастность", "preset_high_contrast")],
        [create_animated_button("Яркое изображение", "preset_bright")],
        [create_animated_button("Чёткость", "preset_sharp")],
        [create_animated_button("Сбалансированный", "preset_balanced")],
        [create_animated_button("◀️ Назад", "back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    await message.answer(
        "Выберите пресет улучшения:\n\n"
        "• Без улучшений - оригинальное изображение\n"
        "• Высокая контрастность - усиление контраста\n"
        "• Яркое изображение - увеличение яркости\n"
        "• Чёткость - улучшение детализации\n"
        "• Сбалансированный - оптимальные настройки",
        reply_markup=reply_markup
    )
    log_action("presets_menu_complete", "Presets menu created successfully")


# Добавляем расширенное логирование для обработчика скриншотов
async def handle_screenshot(message: Message, preset: str = None):
    """Take and process screenshot with animated progress"""
    status_message = None
    tmp_filename = None
    
    try:
        # Create the screenshots directory if it doesn't exist
        screenshots_dir = 'screenshots'
        temp_dir = os.path.join(screenshots_dir, 'temp')
        os.makedirs(screenshots_dir, exist_ok=True)
        os.makedirs(temp_dir, exist_ok=True)

        # Ensure cleanup of old temp files
        for f in os.listdir(temp_dir):
            if f.startswith('screenshot_'):
                try:
                    file_path = os.path.join(temp_dir, f)
                    file_age = datetime.now() - datetime.fromtimestamp(os.path.getctime(file_path))
                    if file_age > timedelta(hours=1):
                        os.unlink(file_path)
                        logger.info(f"Cleaned up old temp file: {f}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp file {f}: {e}")
        log_action("screenshot_start", f"Starting screenshot process with preset: {preset}")

        # Начальное сообщение о статусе
        status_message = await message.answer("🔄 Начинаю создание скриншота...")
        log_action("progress_bar_start", "Showing animated progress bar")

        # Показываем анимированный прогресс-бар
        await animated_progress_bar(status_message)

        # Уведомление о запросе к APIFlash
        await status_message.edit_text("📸 Получаю скриншот таблицы...")
        log_action("apiflash_request", "Requesting screenshot from APIFlash")
        screenshot_data = take_screenshot(SHEET_URL)

        if screenshot_data is None:
            log_action("screenshot_error", "Failed to take screenshot")
            await status_message.edit_text(
                "❌ Извините, не удалось создать скриншот. Пожалуйста, попробуйте позже."
            )
            return

        if preset:
            log_action("preset_apply", f"Applying preset: {preset}")
            # Уведомление о применении пресета
            await status_message.edit_text(f"✨ Применяю пресет улучшения: {preset}...")
            await animated_progress_bar(status_message, total_steps=3)
            screenshot_data = ImageProcessor.process_image(screenshot_data, preset)

        # Уведомление о сохранении и отправке
        await status_message.edit_text("💾 Сохраняю результат...")
        log_action("save_result", "Saving processed screenshot")

        # Создаем временный файл в директории screenshots
        try:
            # Create temporary directory in the project root
            temp_dir = os.path.join('screenshots', 'temp')
            os.makedirs(temp_dir, exist_ok=True)
            tmp_filename = os.path.join(temp_dir, f'screenshot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png')
            logger.info(f"Saving temporary file to: {tmp_filename}")

            try:
                with open(tmp_filename, 'wb') as tmp_file:
                    tmp_file.write(screenshot_data)
                logger.info(f"Screenshot saved successfully to {tmp_filename}")
            except Exception as e:
                logger.error(f"Failed to save screenshot: {e}")
                raise

            logger.info(f"Temporary file created successfully at: {tmp_filename}")
        except Exception as e:
            logger.error(f"Error creating temporary file: {e}")
            raise

        try:
            log_action("send_photo", "Sending processed photo to Telegram")
            preset_names = {
                'high_contrast': 'Высокая контрастность',
                'bright': 'Яркое изображение',
                'sharp': 'Чёткость',
                'balanced': 'Сбалансированный',
                'none': 'Без улучшений'
            }

            # Финальное уведомление об успешном завершении
            await status_message.edit_text("✅ Скриншот готов! Отправляю...")

            caption = "📸 Скриншот таблицы"
            if preset:
                caption += f" ✨ (Пресет: {preset_names.get(preset, preset)})"

            photo = FSInputFile(tmp_filename)
            # Создаем короткий идентификатор для временного файла
            file_id = datetime.now().strftime("%H%M%S")
            keyboard = [[
                InlineKeyboardButton(text="📥 Добавить в архив", callback_data=f"archive_{file_id}")
            ]]
            # Сохраняем путь к файлу во временное хранилище
            temp_files[file_id] = tmp_filename
            await message.answer_photo(
                photo=photo,
                caption=caption,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            await status_message.delete()
            log_action("process_complete", "Screenshot process completed successfully")
        except Exception as e:
            logger.error(f"Error in sending photo: {e}")
            # Clean up temporary file only on error
            if os.path.exists(tmp_filename):
                os.unlink(tmp_filename)
            raise

        # Автоматически показываем главное меню
        await show_main_menu(message)

    except Exception as e:
        error_details = str(e)
        log_action("error", f"Error in screenshot handler: {error_details}")
        
        if status_message:
            try:
                await status_message.edit_text(
                    "❌ Произошла ошибка при создании скриншота. Пожалуйста, попробуйте позже."
                )
            except Exception as e2:
                logger.error(f"Failed to edit error message: {e2}")
                try:
                    await message.answer(
                        "❌ Произошла ошибка при создании скриншота. Пожалуйста, попробуйте позже."
                    )
                except Exception as e3:
                    logger.error(f"Failed to send error message: {e3}")
        
        # Cleanup any temporary files
        if tmp_filename and os.path.exists(tmp_filename):
            try:
                os.unlink(tmp_filename)
                logger.info(f"Cleaned up temporary file after error: {tmp_filename}")
            except Exception as e4:
                logger.error(f"Failed to cleanup temp file: {e4}")

@router.message(F.text == "❓ Помощь")
async def handle_help_button(message: Message):
    """Handle help button press"""
    try:
        help_text = (
            "📋 Доступные команды:\n\n"
            "/start - Запустить бота и открыть главное меню\n"
            "/help - Показать это сообщение\n\n"
            "🔧 Возможности:\n"
            "• Создание скриншотов Google таблиц\n"
            "• Улучшение качества изображения с разными пресетами:\n"
            "  - Высокая контрастность: усиление контраста и чёткости\n"
            "  - Яркое изображение: увеличение яркости\n"
            "  - Чёткость: улучшение детализации\n"
            "  - Сбалансированный: оптимальное соотношение параметров\n\n"
            "Используйте кнопки меню для удобной навигации!"
        )

        keyboard = [
            [InlineKeyboardButton(text="◀️ Вернуться в меню", callback_data='back_to_main')]
        ]
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

        await message.answer(help_text, reply_markup=reply_markup)
        logger.info("Help message sent successfully")
    except Exception as e:
        logger.error(f"Error in help handler: {e}")

@router.callback_query(F.data == 'back_to_main')
async def handle_back_to_main(callback: CallbackQuery):
    """Handle back to main menu button"""
    await callback.answer()
    # Создаем новое сообщение с главным меню вместо редактирования текущего
    await show_main_menu(callback.message)
    # Удаляем предыдущее сообщение с меню
    await callback.message.delete()

@router.callback_query(F.data == 'enhancement_menu')
async def handle_enhancement_menu(callback: CallbackQuery):
    """Show enhancement presets menu"""
    await callback.answer()
    await handle_presets_menu(callback.message)

@router.callback_query(F.data.startswith('preset_'))
async def handle_preset_callback(callback: CallbackQuery):
    """Handle preset selection"""
    try:
        preset = callback.data.replace('preset_', '')
        await callback.answer(f"Создаю скриншот с пресетом {preset}...")
        logger.info(f"Processing screenshot with preset: {preset}")
        await handle_screenshot(callback.message, preset=preset)
    except Exception as e:
        logger.error(f"Error in preset callback handler: {e}")
        await callback.message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@router.callback_query(F.data == "take_screenshot")
async def handle_take_screenshot_callback(callback: CallbackQuery):
    """Handle take screenshot button press from main menu"""
    await callback.answer()
    await handle_screenshot_request(callback.message)

@router.callback_query(F.data == "presets_menu")
async def handle_presets_menu_callback(callback: CallbackQuery):
    """Handle presets menu button press from main menu"""
    await callback.answer()
    await handle_presets_menu(callback.message)

@router.callback_query(F.data == "help_menu")
async def handle_help_menu_callback(callback: CallbackQuery):
    """Handle help button press from main menu"""
    await callback.answer()
    await handle_help_button(callback.message)

@router.callback_query(F.data.startswith("select_"))
async def handle_screenshot_selection(callback: CallbackQuery):
    """Handle screenshot selection for multiple deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        filename = callback.data.replace("select_", "")
        user_key = f"user_{user_id}"
        
        logger.info(f"[SELECTION] Processing selection for file: {filename}")
        logger.info(f"[SELECTION] User key: {user_key}")
        logger.info(f"[SELECTION] Current selected files: {selected_screenshots.get(user_key, set())}")

        # Get all available screenshots
        screenshots = screenshot_storage.get_all_screenshots(user_id, chat_id)
        
        # Check if the file exists in available screenshots
        file_exists = any(os.path.basename(s["filepath"]) == filename for s in screenshots)
        if not file_exists:
            logger.error(f"[SELECTION] File not found: {filename}")
            await callback.answer("❌ Файл не найден")
            return

        # Initialize set if needed
        if user_key not in selected_screenshots:
            selected_screenshots[user_key] = set()

        # Toggle selection using basename
        if filename in selected_screenshots[user_key]:
            selected_screenshots[user_key].remove(filename)
            logger.info(f"[SELECTION] Removed {filename} from selection")
            await callback.answer("❌ Скриншот убран из выбранных")
        else:
            selected_screenshots[user_key].add(filename)
            logger.info(f"[SELECTION] Added {filename} to selection. Current selection: {selected_screenshots[user_key]}")
            await callback.answer("✅ Скриншот добавлен к выбранным")

        # Update interface
        await update_screenshot_message(callback.message, user_id, chat_id)

    except Exception as e:
        logger.error(f"[SELECTION] Error in screenshot selection: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при выборе скриншота")

async def update_screenshot_message(message: Message, user_id: int, chat_id: int):
    """Update message with selected screenshots"""
    try:
        logger.info("[UPDATE_MESSAGE] Starting message update")
        user_key = f"user_{user_id}"
        
        if not message or not message.text:
            logger.error("[UPDATE_MESSAGE] Message or message text is None")
            return

        current_label = None
        if "Категория:" in message.text:
            current_label = message.text.split("Категория:")[1].split("\n")[0].strip()
            logger.info(f"[UPDATE_MESSAGE] Found category: {current_label}")
            screenshots = screenshot_storage.get_screenshots_by_label(current_label, user_id, chat_id)
            logger.info(f"[UPDATE_MESSAGE] Found {len(screenshots)} screenshots")
        else:
            logger.error("[UPDATE_MESSAGE] Cannot find category in message text")
            return

        # Инициализируем множество, если его еще нет
        if user_key not in selected_screenshots:
            selected_screenshots[user_key] = set()

        keyboard = []
        
        # Добавляем кнопки действий, если есть выбранные скриншоты
        if selected_screenshots[user_key]:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"🗑 Удалить выбранные ({len(selected_screenshots[user_key])})",
                    callback_data="delete_selected"
                )
            ])
            logger.info(f"[UPDATE_MESSAGE] Added delete selected button for {len(selected_screenshots[user_key])} files")

        # Добавляем кнопку для удаления всей категории
        if screenshots:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"🗑 Удалить все ({len(screenshots)})",
                    callback_data=f"delete_category_{current_label}"
                )
            ])
            logger.info(f"[UPDATE_MESSAGE] Added delete all button for {len(screenshots)} files")

        # Добавляем кнопки для каждого скриншота
        for screenshot in screenshots:
            filename = os.path.basename(screenshot['filepath'])
            is_selected = filename in selected_screenshots[user_key]
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{screenshot['timestamp']} {'✅' if is_selected else ''}",
                    callback_data=f"select_{filename}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")
        ])

        logger.info("[UPDATE_MESSAGE] Updating message with new keyboard")
        await message.edit_text(
            f"📁 Категория: {current_label}\n"
            "Выберите скриншоты для удаления:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        logger.info("[UPDATE_MESSAGE] Message updated successfully")

    except Exception as e:
        logger.error(f"[UPDATE_MESSAGE] Error updating screenshot message: {e}", exc_info=True)

@router.callback_query(F.data == "view_archive")
async def handle_view_archive(callback: CallbackQuery):
    """Handle archive view button press"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id

        # Получаем все уникальные метки пользователя
        labels = screenshot_storage.get_all_labels(user_id, chat_id)

        keyboard = []
        # Добавляем секцию с метками
        if labels:
            for label in labels:
                screenshots = screenshot_storage.get_screenshots_by_label(label, user_id, chat_id)
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"{label} ({len(screenshots)})",
                        callback_data=f"label_{label}"
                    )
                ])

        # Добавляем кнопки навигации
        keyboard.extend([
            [InlineKeyboardButton(text="📅 По дате", callback_data="view_by_date")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="view_stats")],
            [InlineKeyboardButton(text="🔍 Поиск", callback_data="search_labels")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
        ])

        # Получаем статистику для заголовка
        all_screenshots = screenshot_storage.get_all_screenshots(user_id, chat_id)
        monthly_stats = screenshot_stats.get_monthly_stats(all_screenshots)

        message_text = (
            f"Архив скриншотов\n"
            f"Всего: {len(all_screenshots)} | В этом месяце: {monthly_stats['total_this_month']}\n"
            f"Осталось в этом месяце: {monthly_stats['remaining_limit']}\n\n"
            "Выберите категорию или способ поиска:"
        )

        # Проверяем, есть ли текст в сообщении
        try:
            await callback.message.edit_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
        except Exception as e:
            logger.warning(f"Could not edit message: {e}, sending new message")
            # Если не можем отредактировать, отправляем новое сообщение
            if callback.message:
                await callback.message.delete()
            await callback.message.answer(
                message_text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )

    except Exception as e:
        logger.error(f"Error in archive handler: {e}", exc_info=True)
        try:
            await callback.message.answer(
                "Произошла ошибка при загрузке архива",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
                ])
            )
        except Exception as e2:
            logger.error(f"Error sending error message: {e2}", exc_info=True)

@router.callback_query(F.data.startswith("label_"))
async def handle_label_screenshots(callback: CallbackQuery):
    """Handle showing screenshots for selected label"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        label = callback.data.replace("label_", "")
        screenshots = screenshot_storage.get_screenshots_by_label(label, user_id, chat_id)

        if not screenshots:
            await callback.message.edit_text(
                "В этой категории нет скриншотов",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
                ])
            )
            return

        keyboard = []
        # Добавляем кнопку для удаления всех скриншотов в категории
        keyboard.append([
            InlineKeyboardButton(
                text=f"🗑 Удалить все ({len(screenshots)})",
                callback_data=f"delete_category_{label}"
            )
        ])

        # Добавляем кнопки для каждого скриншота
        for screenshot in screenshots:
            timestamp = screenshot["timestamp"]
            filename = os.path.basename(screenshot['filepath'])
            user_key = f"user_{user_id}"
            is_selected = filename in selected_screenshots[user_key]
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{timestamp} {'✅' if is_selected else ''}",
                    callback_data=f"show_screenshot_{filename}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")
        ])

        await callback.message.edit_text(
            f"📁 Категория: {label}\n"
            "Выберите скриншот для просмотра:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

        await callback.answer()
    except Exception as e:
        logger.error(f"Error showing screenshots: {e}", exc_info=True)
        await callback.message.edit_text(
            "❌ Произошла ошибка при загрузке скриншотов",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
            ])
        )

@router.callback_query(F.data == "delete_selected")
async def handle_delete_selected(callback: CallbackQuery):
    """Handle deletion of selected screenshots"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        user_key = f"user_{user_id}"

        logger.info(f"[DELETE_SELECTED] Starting deletion process for user {user_id}")
        logger.info(f"[DELETE_SELECTED] Selected screenshots: {selected_screenshots.get(user_key, set())}")

        if not selected_screenshots.get(user_key):
            await callback.answer("❌ Нет выбранных скриншотов")
            return

        # Get current label from message
        current_label = None
        if callback.message and callback.message.text:
            if "Категория:" in callback.message.text:
                current_label = callback.message.text.split("Категория:")[1].split("\n")[0].strip()
                logger.info(f"[DELETE_SELECTED] Current category: {current_label}")

        # Get screenshots for the current label and check file existence
        screenshots = screenshot_storage.get_screenshots_by_label(current_label, user_id, chat_id) if current_label else []
        available_files = {os.path.basename(s["filepath"]) for s in screenshots}
        
        logger.info(f"[DELETE_SELECTED] Selected files: {selected_screenshots[user_key]}")
        logger.info(f"[DELETE_SELECTED] Available files in category: {available_files}")
        
        valid_selections = selected_screenshots[user_key].intersection(available_files)
        logger.info(f"[DELETE_SELECTED] Valid selections after intersection: {valid_selections}")

        if not valid_selections:
            await callback.answer("❌ Выбранные скриншоты не найдены")
            return

        # Request confirmation
        keyboard = [
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить", 
                    callback_data=f"confirm_delete_selected"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"cancel_delete_selected"
                )
            ]
        ]

        await callback.message.edit_text(
            f"⚠️ Вы уверены, что хотите удалить {len(valid_selections)} выбранных скриншотов?\n"
            "Это действие нельзя отменить.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"[DELETE_SELECTED] Error in delete selected handler: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")
        try:
            await handle_view_archive(callback)
        except Exception as e2:
            logger.error(f"[DELETE_SELECTED] Error returning to archive: {e2}", exc_info=True)

@router.callback_query(F.data == "confirm_delete_selected")
async def handle_confirm_delete_selected(callback: CallbackQuery):
    """Handle confirmation of selected screenshots deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        user_key = f"user_{user_id}"

        if not selected_screenshots.get(user_key):
            await callback.answer("❌ Нет выбранных скриншотов")
            return

        # Verify selected files exist before starting deletion
        screenshots = screenshot_storage.get_all_screenshots(user_id, chat_id)
        available_files = {os.path.basename(s["filepath"]) for s in screenshots}
        valid_selections = selected_screenshots[user_key].intersection(available_files)

        if not valid_selections:
            await callback.answer("❌ Выбранные скриншоты не найдены")
            return

        # Show deletion status
        status_message = await callback.message.edit_text(
            "🗑 Удаление выбранных скриншотов...\n"
            f"Всего файлов: {len(valid_selections)}\n"
            "⏳ Пожалуйста, подождите..."
        )

        deleted_count = 0
        failed_count = 0
        failed_files = []

        for filename in valid_selections:
            try:
                logger.info(f"[CONFIRM_DELETE_SELECTED] Attempting to delete: {filename}")

                if screenshot_storage.delete_screenshot(filename, user_id, chat_id):
                    deleted_count += 1
                    selected_screenshots[user_key].remove(filename)
                    logger.info(f"[CONFIRM_DELETE_SELECTED] Successfully deleted: {filename}")
                else:
                    failed_count += 1
                    failed_files.append(filename)
                    logger.error(f"[CONFIRM_DELETE_SELECTED] Failed to delete: {filename}")

                # Update status every 5 files
                if (deleted_count + failed_count) % 5 == 0:
                    await status_message.edit_text(
                        "🗑 Удаление выбранных скриншотов...\n"
                        f"Обработано: {deleted_count + failed_count} из {len(valid_selections)}\n"
                        f"✅ Успешно: {deleted_count}\n"
                        f"❌ Ошибок: {failed_count}"
                    )

            except Exception as e:
                failed_count += 1
                failed_files.append(filename)
                logger.error(f"[CONFIRM_DELETE_SELECTED] Error processing {filename}: {e}", exc_info=True)

        # Generate report
        result_text = [
            "📊 Результаты удаления:",
            f"✅ Успешно удалено: {deleted_count}",
            f"❌ Ошибок: {failed_count}"
        ]

        if failed_files:
            result_text.append("\nФайлы с ошибками:")
            for file in failed_files[:5]:
                result_text.append(f"- {file}")
            if len(failed_files) > 5:
                result_text.append(f"...и еще {len(failed_files) - 5} файлов")

        keyboard = [
            [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
        ]

        await status_message.edit_text(
            "\n".join(result_text),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

        logger.info(f"[CONFIRM_DELETE_SELECTED] Deletion completed. Success: {deleted_count}, Failed: {failed_count}")

    except Exception as e:
        logger.error(f"[CONFIRM_DELETE_SELECTED] Error in confirm delete selected: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при удалении")
        try:
            await handle_view_archive(callback)
        except Exception as e2:
            logger.error(f"[CONFIRM_DELETE_SELECTED] Error returning to archive: {e2}", exc_info=True)

@router.callback_query(F.data == "cancel_delete_selected")
async def handle_cancel_delete_selected(callback: CallbackQuery):
    """Handle cancellation of selected screenshots deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        user_key = f"user_{user_id}"

        # Clear selection
        if user_key in selected_screenshots:
            selected_screenshots[user_key].clear()

        await callback.answer("✅ Удаление отменено")
        await handle_view_archive(callback)

    except Exception as e:
        logger.error(f"[CANCEL_DELETE_SELECTED] Error: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")
        try:
            await handle_view_archive(callback)
        except Exception as e2:
            logger.error(f"[CANCEL_DELETE_SELECTED] Error returning to archive: {e2}", exc_info=True)

@router.callback_query(F.data.startswith("confirm_delete_category_"))
async def handle_confirm_delete_category(callback: CallbackQuery):
    """Handle confirmation of category deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        label = callback.data.replace("confirm_delete_category_", "")

        logger.info(f"[CONFIRM_DELETE] Starting deletion of category '{label}' for user {user_id} in chat {chat_id}")

        screenshots = screenshot_storage.get_screenshots_by_label(label, user_id, chat_id)
        logger.info(f"[CONFIRM_DELETE] Found {len(screenshots)} screenshots to delete")
        for screenshot in screenshots:
            logger.info(f"[CONFIRM_DELETE] Will delete: {screenshot['filepath']} with label: {screenshot['label']}")

        if not screenshots:
            logger.warning(f"[CONFIRM_DELETE] No screenshots found in category '{label}'")
            await callback.answer("❌ Нет доступных скриншотов для удаления")
            await handle_view_archive(callback)
            return

        # Показываем статус удаления
        status_message = await callback.message.edit_text(
            "🗑 Удаление скриншотов...\n"
            f"Всего файлов: {len(screenshots)}\n"
            "⏳ Пожалуйста, подождите..."
        )

        deleted_count = 0
        failed_count = 0
        failed_files = []

        for screenshot in screenshots:
            try:
                filename = os.path.basename(screenshot["filepath"])
                logger.info(f"[CONFIRM_DELETE] Attempting to delete: {filename}")

                if screenshot_storage.delete_screenshot(filename, user_id, chat_id):
                    deleted_count += 1
                    logger.info(f"[CONFIRM_DELETE] Successfully deleted: {filename}")
                else:
                    failed_count += 1
                    failed_files.append(filename)
                    logger.error(f"[CONFIRM_DELETE] Failed to delete: {filename}")

                # Обновляем статус каждые 5 файлов
                if (deleted_count + failed_count) % 5 == 0:
                    await status_message.edit_text(
                        "🗑 Удаление скриншотов...\n"
                        f"Обработано: {deleted_count + failed_count} из {len(screenshots)}\n"
                        f"✅ Успешно: {deleted_count}\n"
                        f"❌ Ошибок: {failed_count}"
                    )

            except Exception as e:
                failed_count += 1
                if 'filename' in locals():
                    failed_files.append(filename)
                logger.error(f"[CONFIRM_DELETE] Error deleting file: {e}", exc_info=True)

        # Формируем отчет
        result_text = [
            "📊 Результаты удаления:",
            f"✅ Успешно удалено: {deleted_count}",
            f"❌ Ошибок: {failed_count}"
        ]

        if failed_files:
            result_text.append("\nФайлы с ошибками:")
            for file in failed_files[:5]:
                result_text.append(f"- {file}")
            if len(failed_files) > 5:
                result_text.append(f"...и еще {len(failed_files) - 5} файлов")

        keyboard = [
            [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
        ]

        await status_message.edit_text(
            "\n".join(result_text),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

        logger.info(f"[CONFIRM_DELETE] Category deletion completed. Success: {deleted_count}, Failed: {failed_count}")

    except Exception as e:
        logger.error(f"[CONFIRM_DELETE] Error in confirm delete category: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при удалении категории")
        try:
            await handle_view_archive(callback)
        except Exception as e2:
            logger.error(f"[CONFIRM_DELETE] Error returning to archive: {e2}", exc_info=True)

@router.callback_query(F.data.startswith("show_screenshot_"))
async def handle_show_screenshot(callback: CallbackQuery):
    """Handle showing specific screenshot"""
    try:
        logger.info(f"Showing screenshot: {callback.data}")
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        filename = callback.data.replace("show_screenshot_", "")
        user_key = f"user_{user_id}"

        screenshots = screenshot_storage.get_all_screenshots(user_id, chat_id)
        screenshot_info = None

        for screenshot in screenshots:
            if os.path.basename(screenshot["filepath"]) == filename:
                screenshot_info = screenshot
                break

        if screenshot_info and os.path.exists(screenshot_info["filepath"]):
            photo = FSInputFile(screenshot_info["filepath"])

            # Добавляем кнопку выбора и навигации
            date = screenshot_info["timestamp"].split()[0]
            is_selected = filename in selected_screenshots[user_key]

            keyboard = [
                [
                    InlineKeyboardButton(
                        text="✅ Выбран" if is_selected else "☑️ Выбрать",
                        callback_data=f"select_{filename}"
                    ),
                    InlineKeyboardButton(
                        text="🗑 Удалить",
                        callback_data=f"delete_{filename}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 К списку",
                        callback_data="view_archive"
                    )
                ]
            ]

            # Добавляем кнопку удаления выбранных, если есть выбранные скриншоты
            if len(selected_screenshots[user_key]) > 0:
                keyboard.insert(0, [
                    InlineKeyboardButton(
                        text=f"🗑 Удалить выбранные ({len(selected_screenshots[user_key])})",
                        callback_data="delete_selected"
                    )
                ])

            await callback.message.delete()
            await callback.message.answer_photo(
                photo=photo,
                caption=f"{screenshot_info['label']}\n{screenshot_info['timestamp']}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            logger.info(f"Successfully showed screenshot: {filename}")
        else:
            logger.error(f"Screenshot not found: {filename}")
            await callback.answer("Скриншот не найден")
            await callback.message.edit_text(
                "Скриншот не найден",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
                ])
            )

    except Exception as e:
        logger.error(f"Error showing screenshot: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при загрузке скриншота")
        await callback.message.edit_text(
            "Произошла ошибка при загрузке скриншота",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
            ])
        )

@router.callback_query(F.data.startswith("delete_"))
async def handle_delete_screenshot(callback: CallbackQuery):
    """Handle screenshot deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        
        # Handle both category deletion and single file deletion
        if callback.data.startswith("delete_category_"):
            await handle_delete_category(callback)
            return
            
        filename = callback.data.replace("delete_", "")
        
        logger.info(f"[DELETE] Handling deletion request for file: {filename}")
        logger.info(f"[DELETE] Original callback data: {callback.data}")

        # Проверяем наличие файла
        screenshots = screenshot_storage.get_all_screenshots(user_id, chat_id)
        file_exists = any(os.path.basename(s["filepath"]) == filename for s in screenshots)
        
        if not file_exists:
            logger.error(f"[DELETE] File not found: {filename}")
            await callback.answer("❌ Файл не найден")
            return

        # Handle deletion
        if screenshot_storage.delete_screenshot(filename, user_id, chat_id):
            await callback.answer("✅ Скриншот удален")
            logger.info(f"[DELETE] Successfully deleted screenshot: {filename}")
            await handle_view_archive(callback)
        else:
            await callback.answer("❌ Не удалось удалить скриншот")
            logger.error(f"[DELETE] Failed to delete screenshot: {filename}")

    except Exception as e:
        logger.error(f"[DELETE] Error in delete screenshot handler: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")
        try:
            await handle_view_archive(callback)
        except Exception as e2:
            logger.error(f"[DELETE] Error returning to archive: {e2}", exc_info=True)


@router.callback_query(F.data.startswith("delete_category_"))
async def handle_delete_category(callback: CallbackQuery):
    """Handle deletion of all screenshots in a category"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        label = callback.data.replace("delete_category_", "")
        
        logger.info(f"[DELETE_CATEGORY] Starting deletion process for category '{label}'")
        logger.info(f"[DELETE_CATEGORY] User ID: {user_id}, Chat ID: {chat_id}")
        
        # Получаем все скриншоты в категории
        screenshots = screenshot_storage.get_screenshots_by_label(label, user_id, chat_id)
        logger.info(f"[DELETE_CATEGORY] Found {len(screenshots)} screenshots in category")
        for screenshot in screenshots:
            logger.info(f"[DELETE_CATEGORY] Found screenshot: {screenshot['filepath']} with label: {screenshot['label']}")

        if not screenshots:
            logger.warning(f"[DELETE_CATEGORY] No screenshots found in category '{label}'")
            await callback.answer("❌ Нет скриншотов для удаления")
            return

        # Запрашиваем подтверждение
        keyboard = [
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"confirm_delete_category_{label}"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"label_{label}"
                )
            ]
        ]

        await callback.message.edit_text(
            f"⚠️ Вы уверены, что хотите удалить ВСЕ скриншоты из категории \"{label}\"?\n"
            f"Всего скриншотов: {len(screenshots)}\n"
            "Это действие нельзя отменить.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"[DELETE_CATEGORY] Error in delete category handler: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")
        try:
            await handle_view_archive(callback)
        except Exception as e2:
            logger.error(f"[DELETE_CATEGORY] Error returning to archive: {e2}", exc_info=True)

@router.callback_query(F.data.startswith("confirm_delete_category_"))
async def handle_confirm_delete_category(callback: CallbackQuery):
    """Handle confirmation of category deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        label = callback.data.replace("confirm_delete_category_", "")

        logger.info(f"[CONFIRM_DELETE] Starting deletion of category '{label}' for user {user_id} in chat {chat_id}")

        screenshots = screenshot_storage.get_screenshots_by_label(label, user_id, chat_id)
        logger.info(f"[CONFIRM_DELETE] Found {len(screenshots)} screenshots to delete")

        if not screenshots:
            logger.warning(f"[CONFIRM_DELETE] No screenshots found in category '{label}'")
            await callback.answer("❌ Нет доступных скриншотов для удаления")
            await handle_view_archive(callback)
            return

        # Показываем статус удаления
        status_message = await callback.message.edit_text(
            f"🗑 Удаление категории '{label}'...\n"
            f"Всего файлов: {len(screenshots)}\n"
            "⏳ Пожалуйста, подождите..."
        )

        deleted_count = 0
        failed_count = 0
        failed_files = []

        for screenshot in screenshots:
            try:
                # Используем только имя файла из полного пути
                filename = os.path.basename(screenshot["filepath"])
                logger.info(f"[CONFIRM_DELETE] Attempting to delete: {filename}")

                if screenshot_storage.delete_screenshot(filename, user_id, chat_id):
                    deleted_count += 1
                    logger.info(f"[CONFIRM_DELETE] Successfully deleted: {filename}")
                else:
                    failed_count += 1
                    failed_files.append(filename)
                    logger.error(f"[CONFIRM_DELETE] Failed to delete: {filename}")

                # Обновляем статус каждые 5 файлов
                if (deleted_count + failed_count) % 5 == 0:
                    await status_message.edit_text(
                        f"🗑 Удаление категории '{label}'...\n"
                        f"Обработано: {deleted_count + failed_count} из {len(screenshots)}\n"
                        f"✅ Успешно: {deleted_count}\n"
                        f"❌ Ошибок: {failed_count}"
                    )

            except Exception as e:
                failed_count += 1
                if 'filename' in locals():
                    failed_files.append(filename)
                logger.error(f"[CONFIRM_DELETE] Error deleting file: {e}", exc_info=True)

        # Формируем отчет
        result_text = [
            f"📊 Результаты удаления категории '{label}':",
            f"✅ Успешно удалено: {deleted_count}",
            f"❌ Ошибок: {failed_count}"
        ]

        if failed_files:
            result_text.append("\nФайлы с ошибками:")
            for file in failed_files[:5]:
                result_text.append(f"- {file}")
            if len(failed_files) > 5:
                result_text.append(f"...и еще {len(failed_files) - 5} файлов")

        keyboard = [
            [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
        ]

        await status_message.edit_text(
            "\n".join(result_text),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

        logger.info(f"[CONFIRM_DELETE] Category deletion completed. Success: {deleted_count}, Failed: {failed_count}")

    except Exception as e:
        logger.error(f"[CONFIRM_DELETE] Error in confirm delete category: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при удалении категории")
        try:
            await handle_view_archive(callback)
        except Exception as e2:
            logger.error(f"[CONFIRM_DELETE] Error returning to archive: {e2}", exc_info=True)

@router.callback_query(F.data == "delete_selected")
async def handle_delete_selected(callback: CallbackQuery):
    """Handle deletion of selected screenshots"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        user_key = f"user_{user_id}"

        if not selected_screenshots[user_key]:
            await callback.answer("❌ Нет выбранных скриншотов")
            return

        # Запрашиваем подтверждение
        keyboard = [
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data="confirm_delete_selected"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="cancel_delete_selected"
                )
            ]
        ]

        await callback.message.edit_text(
            f"⚠️ Вы уверены, что хотите удалить {len(selected_screenshots[user_key])} выбранных скриншотов?\n"
            "Это действие нельзя отменить.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"[DELETE_SELECTED] Error in delete selected handler: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")

@router.callback_query(F.data == "confirm_delete_selected")
async def handle_confirm_delete_selected(callback: CallbackQuery):
    """Handle confirmation of selected screenshots deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        user_key = f"user_{user_id}"

        logger.info(f"[CONFIRM_DELETE_SELECTED] Starting deletion of {len(selected_screenshots[user_key])} screenshots")

        # Показываем статус удаления
        status_message = await callback.message.edit_text(
            "🗑 Удаление выбранных скриншотов...\n"
            f"Всего файлов: {len(selected_screenshots[user_key])}\n"
            "⏳ Пожалуйста, подождите..."
        )

        deleted_count = 0
        failed_count = 0
        failed_files = []

        for filename in list(selected_screenshots[user_key]):  # Создаем копию списка
            try:
                logger.info(f"[CONFIRM_DELETE_SELECTED] Processing file: {filename}")

                if screenshot_storage.delete_screenshot(filename, user_id, chat_id):
                    deleted_count += 1
                    selected_screenshots[user_key].remove(filename)  # Удаляем из выбранных
                    logger.info(f"[CONFIRM_DELETE_SELECTED] Successfully deleted: {filename}")
                else:
                    failed_count += 1
                    failed_files.append(filename)
                    logger.error(f"[CONFIRM_DELETE_SELECTED] Failed to delete: {filename}")

                # Обновляем статус каждые 5 файлов
                if (deleted_count + failed_count) % 5 == 0:
                    await status_message.edit_text(
                        "🗑 Удаление выбранных скриншотов...\n"
                        f"Обработано: {deleted_count + failed_count} из {len(selected_screenshots[user_key])}\n"
                        f"✅ Успешно: {deleted_count}\n"
                        f"❌ Ошибок: {failed_count}"
                    )

            except Exception as e:
                failed_count += 1
                failed_files.append(filename)
                logger.error(f"[CONFIRM_DELETE_SELECTED] Error processing {filename}: {e}", exc_info=True)

        # Формируем отчет
        result_text = [
            "📊 Результаты удаления:",
            f"✅ Успешно удалено: {deleted_count}",
            f"❌ Ошибок: {failed_count}"
        ]

        if failed_files:
            result_text.append("\nФайлы с ошибками:")
            for file in failed_files[:5]:
                result_text.append(f"- {file}")
            if len(failed_files) > 5:
                result_text.append(f"...и еще {len(failed_files) - 5} файлов")

        keyboard = [
            [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
        ]

        await status_message.edit_text(
            "\n".join(result_text),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

        logger.info(f"[CONFIRM_DELETE_SELECTED] Deletion completed. Success: {deleted_count}, Failed: {failed_count}")

    except Exception as e:
        logger.error(f"[CONFIRM_DELETE_SELECTED] Error in confirm delete selected: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при удалении")
        try:
            await handle_view_archive(callback)
        except Exception as e2:
            logger.error(f"[CONFIRM_DELETE_SELECTED] Error returning to archive: {e2}", exc_info=True)

@router.callback_query(F.data.startswith("confirm_delete_category_"))
async def handle_confirm_delete_category(callback: CallbackQuery):
    """Handle confirmation of category deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        label = callback.data.replace("confirm_delete_category_", "")

        logger.info(f"[CONFIRM_DELETE] Starting deletion of category '{label}' for user {user_id} in chat {chat_id}")
        logger.info(f"[CONFIRM_DELETE] Callback data: {callback.data}")

        screenshots = screenshot_storage.get_screenshots_by_label(label, user_id, chat_id)
        logger.info(f"[CONFIRM_DELETE] Found {len(screenshots)} screenshots to delete")

        if not screenshots:
            logger.warning(f"[CONFIRM_DELETE] No screenshots found in category '{label}'")
            await callback.answer("❌ Нет доступных скриншотов для удаления")
            await handle_view_archive(callback)
            return

        # Показываем статус удаления
        status_message = await callback.message.edit_text(
            f"🗑 Удаление категории '{label}'...\n"
            f"Всего файлов: {len(screenshots)}\n"
            "⏳ Пожалуйста, подождите..."
        )

        deleted_count = 0
        failed_count = 0
        failed_files = []

        for screenshot in screenshots:
            try:
                filename = os.path.basename(screenshot["filepath"])
                logger.info(f"[CONFIRM_DELETE] Attempting to delete: {filename}")

                if screenshot_storage.delete_screenshot(filename, user_id, chat_id):
                    deleted_count += 1
                    logger.info(f"[CONFIRM_DELETE] Successfully deleted: {filename}")
                else:
                    failed_count += 1
                    failed_files.append(filename)
                    logger.error(f"[CONFIRM_DELETE] Failed to delete: {filename}")

                # Обновляем статус каждые 5 файлов
                if (deleted_count + failed_count) % 5 == 0:
                    await status_message.edit_text(
                        f"🗑 Удаление категории '{label}'...\n"
                        f"Обработано: {deleted_count + failed_count} из {len(screenshots)}\n"
                        f"✅ Успешно: {deleted_count}\n"
                        f"❌ Ошибок: {failed_count}"
                    )

            except Exception as e:
                failed_count += 1
                # Only add the filename to failed_files if we have it
                if 'filename' in locals():
                    failed_files.append(filename)
                    logger.error(f"[CONFIRM_DELETE] Error deleting {filename}: {e}", exc_info=True)
                else:
                    logger.error(f"[CONFIRM_DELETE] Error processing screenshot: {e}", exc_info=True)

        # Формируем отчет
        result_text = [
            f"📊 Результаты удаления категории '{label}':",
            f"✅ Успешно удалено: {deleted_count}",
            f"❌ Ошибок: {failed_count}"
        ]

        if failed_files:
            result_text.append("\nФайлы с ошибками:")
            for file in failed_files[:5]:
                result_text.append(f"- {file}")
            if len(failed_files) > 5:
                result_text.append(f"...и еще {len(failed_files) - 5} файлов")

        keyboard = [
            [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
        ]

        await status_message.edit_text(
            "\n".join(result_text),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

        logger.info(f"[CONFIRM_DELETE] Category deletion completed. Success: {deleted_count}, Failed: {failed_count}")

    except Exception as e:
        logger.error(f"[CONFIRM_DELETE] Error in confirm delete category: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при удалении категории")
        try:
            await handle_view_archive(callback)
        except Exception as e2:
            logger.error(f"[CONFIRM_DELETE] Error returning to archive: {e2}", exc_info=True)

@router.callback_query(F.data == "confirm_delete_selected")
async def handle_confirm_delete_selected(callback: CallbackQuery):
    """Handle confirmation of selected screenshots deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        user_key = f"user_{user_id}"

        if not selected_screenshots[user_key]:
            await callback.answer("❌ Нет выбранных скриншотов")
            return

        # Показываем статус удаления
        status_message = await callback.message.edit_text(
            "🗑 Удаление выбранных скриншотов...\n"
            f"Всего файлов: {len(selected_screenshots[user_key])}\n"
            "⏳ Пожалуйста, подождите..."
        )

        deleted_count = 0
        failed_count = 0
        failed_files = []

        for filename in list(selected_screenshots[user_key]):  # Создаем копию списка
            try:
                logger.info(f"Attempting to delete selected screenshot: {filename}")
                if screenshot_storage.delete_screenshot(filename, user_id, chat_id):
                    deleted_count += 1
                    selected_screenshots[user_key].remove(filename)  # Удаляем из выбранных
                    logger.info(f"Successfully deleted selected screenshot: {filename}")
                else:
                    failed_count += 1
                    failed_files.append(filename)
                    logger.error(f"Failed to delete selected screenshot: {filename}")

                # Обновляем статус каждые 5 файлов
                if (deleted_count + failed_count) % 5 == 0:
                    await status_message.edit_text(
                        "🗑 Удаление выбранных скриншотов...\n"
                        f"Обработано: {deleted_count + failed_count} из {len(selected_screenshots[user_key])}\n"
                        f"✅ Успешно: {deleted_count}\n"
                        f"❌ Ошибок: {failed_count}"
                    )

            except Exception as e:
                failed_count += 1
                failed_files.append(filename)
                logger.error(f"Error deleting selected screenshot {filename}: {e}", exc_info=True)

        # Формируем отчет
        result_text = [
            "📊 Результаты удаления:",
            f"✅ Успешно удалено: {deleted_count}",
            f"❌ Ошибок: {failed_count}"
        ]

        if failed_files:
            result_text.append("\nФайлы с ошибками:")
            for file in failed_files[:5]:
                result_text.append(f"- {file}")
            if len(failed_files) > 5:
                result_text.append(f"...и еще {len(failed_files) - 5} файлов")

        keyboard = [
            [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
        ]

        await status_message.edit_text(
            "\n".join(result_text),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error in confirm delete selected: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при удалении")
        try:
            await handle_view_archive(callback)
        except Exception as e2:
            logger.error(f"Error returning to archive: {e2}", exc_info=True)

# Update screenshot message function
async def update_screenshot_message(message: Message, user_id: int, chat_id: int):
    """Update message with selected screenshots"""
    try:
        user_key = f"user_{user_id}"
        # Текущая метка из сообщения
        if not message.text:
            logger.error("Message text is empty")
            return
            
        current_label = None
        if "Категория:" in message.text:
            current_label = message.text.split("Категория:")[1].split("\n")[0].strip()
            screenshots = screenshot_storage.get_screenshots_by_label(current_label, user_id, chat_id)
        else:
            logger.error("Cannot find category in message text")
            return

        keyboard = []
        
        # Добавляем кнопки действий, если есть выбранные скриншоты
        if selected_screenshots[user_key]:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"🗑 Удалить выбранные ({len(selected_screenshots[user_key])})",
                    callback_data="delete_selected"
                )
            ])

        # Добавляем кнопку для удаления всей категории
        keyboard.append([
            InlineKeyboardButton(
                text=f"🗑 Удалить все ({len(screenshots)})",
                callback_data=f"delete_category_{current_label}"
            )
        ])

        # Добавляем кнопки для каждого скриншота
        for screenshot in screenshots:
            filename = os.path.basename(screenshot['filepath'])
            is_selected = filename in selected_screenshots[user_key]
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{screenshot['timestamp']} {'✅' if is_selected else ''}",
                    callback_data=f"select_{filename}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")
        ])

        await message.edit_text(
            f"📁 Категория: {current_label}\n"
            "Выберите скриншоты для удаления:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error updating screenshot message: {e}", exc_info=True)
@router.callback_query(F.data == "search_labels")
async def handle_search_request(callback: CallbackQuery):
    """Handle label search request"""
    await callback.message.edit_text(
        "🔍 Отправьте текст для поиска по меткам:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к архиву", callback_data="view_archive")]
        ])
    )
    # Store state for next message
    temp_files[f"search_{callback.from_user.id}"] = True

@router.message(lambda msg: f"search_{msg.from_user.id}" in temp_files)
async def handle_search_query(message: Message):
    """Handle search query"""
    try:
        del temp_files[f"search_{message.from_user.id}"]
        screenshots = screenshot_storage.search_by_label(message.text)

        if not screenshots:
            await message.reply(
                "🔍 Ничего не найдено",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад к архиву", callback_data="view_archive")]
                ])
            )
            return

        await message.reply(
            f"🔍 Найдено скриншотов: {len(screenshots)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад к архиву", callback_data="view_archive")]
            ])
        )

        for screenshot in screenshots:
            if os.path.exists(screenshot["filepath"]):
                photo = FSInputFile(screenshot["filepath"])
                keyboard = [[InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"delete_{os.path.basename(screenshot['filepath'])}"
                )]]
                await message.answer_photo(
                    photo=photo,
                    caption=f"📸 {screenshot['label']}\n📅 {screenshot['timestamp']}",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
                )

    except Exception as e:
        logger.error(f"Error handling search: {e}")
        await message.reply("❌ Произошла ошибка при поиске")

@router.callback_query(F.data == "about")
async def handle_about_callback(callback: CallbackQuery):
    """Handle about button press"""
    try:
        await callback.answer()
        about_text = (
            "О боте:\n\n"
            "Google Sheets Screenshot Bot\n"
            "Создан для удобного получения скриншотов Google таблиц\n\n"
            "Возможности:\n"
            "• Создание качественных скриншотов\n"
            "• Улучшение изображений разными пресетами\n"
            "• Удобное хранение в архиве\n"
            "• Автоматические скриншоты по расписанию\n\n"
            "Для начала работы используйте команду /start"
        )

        keyboard = [[InlineKeyboardButton(text="Назад", callback_data="back_to_main")]]
        await callback.message.edit_text(
            about_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
    except Exception as e:
        logger.error(f"Error in about callback: {e}")
        await callback.message.edit_text("Произошла ошибка")

@router.callback_query(F.data.startswith("archive_"))
async def handle_archive_screenshot(callback: CallbackQuery):
    """Handle archiving a screenshot sent by bot"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        file_id = callback.data.replace("archive_", "")
        filepath = temp_files.get(file_id)

        if not filepath:
            logger.error(f"File not found in temp_files for ID: {file_id}")
            await callback.answer("❌ Файл не найден")
            return

        if not os.path.exists(filepath):
            logger.error(f"File does not exist at path: {filepath}")
            await callback.answer("❌ Файл не найден на диске")
            return

        # Запрашиваем у пользователя метку для сохранения
        keyboard = [
            [InlineKeyboardButton(text="Сохранить автоматически", callback_data=f"autosave_{file_id}")],
            [InlineKeyboardButton(text="Указать свою метку", callback_data=f"customlabel_{file_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel_archive")]
        ]

        await callback.message.reply(
            "Выберите способ сохранения скриншота в архив:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error in archive screenshot handler: {e}")
        await callback.answer("❌ Ошибка при сохранении")


@router.callback_query(F.data.startswith("autosave_"))
async def handle_autosave(callback: CallbackQuery):
    """Handle automatic saving with timestamp"""
    try:
        file_id= callback.data.replace("autosave_", "")
        filepath = temp_files.get(file_id)
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id

        timestamp = datetime.now(pytz.UTC).strftime("%Y-%m-%d %H:%M:%S")
        label = f"Сохранено вручную {timestamp}"

        with open(filepath, 'rb') as f:
            screenshot_data = f.read()

        saved_path = screenshot_storage.save_screenshot(
            screenshot_data, label, user_id, chat_id
        )

        if saved_path:
            await callback.answer("✅ Скриншот сохранен в архив")
            await cleanup_temp_file(filepath, file_id)
        else:
            await callback.answer("❌ Ошибка при сохранении")

    except Exception as e:
        logger.error(f"Error in autosave handler: {e}")
        await callback.answer("❌ Ошибка при сохранении")

@router.callback_query(F.data.startswith("customlabel_"))
async def handle_custom_label_request(callback: CallbackQuery):
    """Handle request for custom label"""
    try:
        file_id = callback.data.replace("customlabel_", "")
        # Сохраняем ID файла во временном хранилище
        temp_files[f"labeling_{callback.from_user.id}"] = file_id

        await callback.message.reply(
            "📝 Введите метку для сохранения скриншота:"
        )
    except Exception as e:
        logger.error(f"Error in custom label handler: {e}")
        await callback.answer("❌ Ошибка при обработке запроса")

@router.message(lambda msg: f"labeling_{msg.from_user.id}" in temp_files)
async def handle_custom_label(message: Message):
    """Handle custom label input"""
    try:
        file_id = temp_files.pop(f"labeling_{message.from_user.id}")
        filepath = temp_files.get(file_id)
        user_id = message.from_user.id
        chat_id = message.chat.id

        if not filepath or not os.path.exists(filepath):
            await message.reply("❌ Скриншот не найден")
            return

        with open(filepath, 'rb') as f:
            screenshot_data = f.read()

        saved_path = screenshot_storage.save_screenshot(
            screenshot_data, message.text, user_id, chat_id
        )

        if saved_path:
            await message.reply("✅ Скриншот сохранен с указанной меткой")
            await cleanup_temp_file(filepath, file_id)
        else:
            await message.reply("❌ Ошибка при сохранении")

    except Exception as e:
        logger.error(f"Error saving with custom label: {e}")
        await message.reply("❌ Произошла ошибка")

async def cleanup_temp_file(filepath: str, file_id: str):
    """Clean up temporary file and its reference"""
    try:
        os.remove(filepath)
        del temp_files[file_id]
        logger.info(f"Temporary file removed: {filepath}")
    except Exception as e:
        logger.error(f"Error removing temporary file: {e}")

@router.callback_query(F.data == "cancel_archive")
async def handle_cancel_archive(callback: CallbackQuery):
    """Handle archive cancellation"""
    await callback.answer("❌ Архивирование отменено")
    await callback.message.delete()

@router.callback_query(F.data.startswith("date_"))
async def handle_date_screenshots(callback: CallbackQuery):
    """Handle showing screenshots for selected date"""
    try:
        logger.info(f"Processing date screenshots request: {callback.data}")
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        date = callback.data.replace("date_", "")

        logger.info(f"Fetching screenshots for date {date}, user {user_id}, chat {chat_id}")
        screenshots = screenshot_storage.get_screenshots_by_date(date, user_id, chat_id)

        if not screenshots:
            logger.info(f"No screenshots found for date {date}")
            await callback.message.edit_text(
                "За эту дату нет скриншотов",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
                ])
            )
            return

        logger.info(f"Found {len(screenshots)} screenshots for date {date}")
        keyboard = []
        for screenshot in screenshots:
            # Получаем время из timestamp безопасным способом
            try:
                timestamp_parts = screenshot["timestamp"].split()
                time_part = timestamp_parts[1] if len(timestamp_parts) > 1 else "00:00"
            except Exception as e:
                logger.error(f"Error parsing timestamp {screenshot['timestamp']}: {e}")
                time_part = "00:00"

            filename = os.path.basename(screenshot['filepath'])
            user_key = f"user_{user_id}"
            is_selected = filename in selected_screenshots[user_key]
            keyboard.append([InlineKeyboardButton(
                text=f"{screenshot['label']} ({time_part}) {'✅' if is_selected else ''}",
                callback_data=f"show_screenshot_{filename}"
            )])

        keyboard.append([InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")])

        await callback.message.edit_text(
            f"Скриншоты за {date}\n"
            "Выберите скриншот для просмотра:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

        await callback.answer()
    except Exception as e:
        logger.error(f"Error showing date screenshots: {e}", exc_info=True)
        await callback.message.edit_text(
            "Произошла ошибка при загрузке скриншотов. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
            ])
        )

@router.callback_query(F.data.startswith("delete_"))
async def handle_delete_screenshot(callback: CallbackQuery):
    """Handle screenshot deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        filename = callback.data.replace("delete_", "")

        logger.info(f"Attempting to delete screenshot: {filename} for user {user_id} in chat {chat_id}")

        if screenshot_storage.delete_screenshot(filename, user_id, chat_id):
            logger.info(f"Successfully deleted screenshot: {filename}")
            await callback.answer("✅ Скриншот удален")
            # Remove the message with the deleted screenshot
            await callback.message.delete()
        else:
            logger.error(f"Failed to delete screenshot: {filename}")
            await callback.answer("❌ Ошибка при удалении")
    except Exception as e:
        logger.error(f"Error in delete handler: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при удалении")

@router.callback_query(F.data == "search_labels")
async def handle_search_request(callback: CallbackQuery):
    """Handle label search request"""
    await callback.message.edit_text(
        "🔍 Отправьте текст для поиска по меткам:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к архиву", callback_data="view_archive")]
        ])
    )
    # Store state for next message
    temp_files[f"search_{callback.from_user.id}"] = True

@router.message(lambda msg: f"search_{msg.from_user.id}" in temp_files)
async def handle_search_query(message: Message):
    """Handle search query"""
    try:
        del temp_files[f"search_{message.from_user.id}"]
        screenshots = screenshot_storage.search_by_label(message.text)

        if not screenshots:
            await message.reply(
                "🔍 Ничего не найдено",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад к архиву", callback_data="view_archive")]
                ])
            )
            return

        await message.reply(
            f"🔍 Найдено скриншотов: {len(screenshots)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад к архиву", callback_data="view_archive")]
            ])
        )

        for screenshot in screenshots:
            if os.path.exists(screenshot["filepath"]):
                photo = FSInputFile(screenshot["filepath"])
                keyboard = [[InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"delete_{os.path.basename(screenshot['filepath'])}"
                )]]
                await message.answer_photo(
                    photo=photo,
                    caption=f"📸 {screenshot['label']}\n📅 {screenshot['timestamp']}",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
                )

    except Exception as e:
        logger.error(f"Error handling search: {e}")
        await message.reply("❌ Произошла ошибка при поиске")

@router.callback_query(F.data == "about")
async def handle_about_callback(callback: CallbackQuery):
    """Handle about button press"""
    try:
        await callback.answer()
        about_text = (
            "О боте:\n\n"
            "Google Sheets Screenshot Bot\n"
            "Создан для удобного получения скриншотов Google таблиц\n\n"
            "Возможности:\n"
            "• Создание качественных скриншотов\n"
            "• Улучшение изображений разными пресетами\n"
            "• Удобное хранение в архиве\n"
            "• Автоматические скриншоты по расписанию\n\n"
            "Для начала работы используйте команду /start"
        )

        keyboard = [[InlineKeyboardButton(text="Назад", callback_data="back_to_main")]]
        await callback.message.edit_text(
            about_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
    except Exception as e:
        logger.error(f"Error in about callback: {e}")
        await callback.message.edit_text("Произошла ошибка")

@router.callback_query(F.data.startswith("archive_"))
async def handle_archive_screenshot(callback: CallbackQuery):
    """Handle archiving a screenshot sent by bot"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        file_id = callback.data.replace("archive_", "")
        filepath = temp_files.get(file_id)

        if not filepath:
            logger.error(f"File not found in temp_files for ID: {file_id}")
            await callback.answer("❌ Файл не найден")
            return

        if not os.path.exists(filepath):
            logger.error(f"File does not exist at path: {filepath}")
            await callback.answer("❌ Файл не найден на диске")
            return

        # Запрашиваем у пользователя метку для сохранения
        keyboard = [
            [InlineKeyboardButton(text="Сохранить автоматически", callback_data=f"autosave_{file_id}")],
            [InlineKeyboardButton(text="Указать свою метку", callback_data=f"customlabel_{file_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel_archive")]
        ]

        await callback.message.reply(
            "Выберите способ сохранения скриншота в архив:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error in archive screenshot handler: {e}")
        await callback.answer("❌ Ошибка при сохранении")


@router.callback_query(F.data.startswith("autosave_"))
async def handle_autosave(callback: CallbackQuery):
    """Handle automatic saving with timestamp"""
    try:
        file_id= callback.data.replace("autosave_", "")
        filepath = temp_files.get(file_id)
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id

        timestamp = datetime.now(pytz.UTC).strftime("%Y-%m-%d %H:%M:%S")
        label = f"Сохранено вручную {timestamp}"

        with open(filepath, 'rb') as f:
            screenshot_data = f.read()

        saved_path = screenshot_storage.save_screenshot(
            screenshot_data, label, user_id, chat_id
        )

        if saved_path:
            await callback.answer("✅ Скриншот сохранен в архив")
            await cleanup_temp_file(filepath, file_id)
        else:
            await callback.answer("❌ Ошибка при сохранении")

    except Exception as e:
        logger.error(f"Error in autosave handler: {e}")
        await callback.answer("❌ Ошибка при сохранении")

@router.callback_query(F.data.startswith("customlabel_"))
async def handle_custom_label_request(callback: CallbackQuery):
    """Handle request for custom label"""
    try:
        file_id = callback.data.replace("customlabel_", "")
        # Сохраняем ID файла во временном хранилище
        temp_files[f"labeling_{callback.from_user.id}"] = file_id

        await callback.message.reply(
            "📝 Введите метку для сохранения скриншота:"
        )
    except Exception as e:
        logger.error(f"Error in custom label handler: {e}")
        await callback.answer("❌ Ошибка при обработке запроса")

@router.message(lambda msg: f"labeling_{msg.from_user.id}" in temp_files)
async def handle_custom_label(message: Message):
    """Handle custom label input"""
    try:
        file_id = temp_files.pop(f"labeling_{message.from_user.id}")
        filepath = temp_files.get(file_id)
        user_id = message.from_user.id
        chat_id = message.chat.id

        if not filepath or not os.path.exists(filepath):
            await message.reply("❌ Скриншот не найден")
            return

        with open(filepath, 'rb') as f:
            screenshot_data = f.read()

        saved_path = screenshot_storage.save_screenshot(
            screenshot_data, message.text, user_id, chat_id
        )

        if saved_path:
            await message.reply("✅ Скриншот сохранен с указанной меткой")
            await cleanup_temp_file(filepath, file_id)
        else:
            await message.reply("❌ Ошибка при сохранении")

    except Exception as e:
        logger.error(f"Error saving with custom label: {e}")
        await message.reply("❌ Произошла ошибка")

@router.callback_query(F.data.startswith("delete_category_"))
async def handle_delete_category(callback: CallbackQuery):
    """Handle deletion of all screenshots in a category"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        label = callback.data.replace("delete_category_", "")

        # Запрашиваем подтверждение
        keyboard = [
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"confirm_delete_category_{label}"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"label_{label}"
                )
            ]
        ]

        await callback.message.edit_text(
            f"⚠️ Вы уверены, что хотите удалить ВСЕ скриншоты из категории \"{label}\"?\n"
            "Это действие нельзя отменить.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error in delete category handler: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")

@router.callback_query(F.data.startswith("confirm_delete_category_"))
async def handle_confirm_delete_category(callback: CallbackQuery):
    """Handle confirmation of category deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        label = callback.data.replace("confirm_delete_category_", "")

        logger.info(f"Starting deletion of category '{label}' for user {user_id} in chat {chat_id}")

        screenshots = screenshot_storage.get_screenshots_by_label(label, user_id, chat_id)

        if not screenshots:
            logger.warning(f"No screenshots found in category '{label}'")
            await callback.answer("❌ Нет скриншотов для удаления")
            # Возвращаемся в архив
            await handle_view_archive(callback)
            return

        logger.info(f"Found {len(screenshots)} screenshots to delete in category '{label}'")

        deleted_count = 0
        failed_count = 0
        failed_files = []

        # Process deletion
        status_message = await callback.message.edit_text(
            f"🗑 Удаление категории '{label}'...\n"
            f"Всего файлов: {len(screenshots)}\n"
            "⏳ Пожалуйста, подождите..."
        )

        for screenshot in screenshots:
            try:
                # Получаем именно имя файла из пути
                filepath = screenshot["filepath"]
                filename = os.path.basename(filepath)
                logger.info(f"Attempting to delete screenshot: {filename} from path: {filepath}")

                if screenshot_storage.delete_screenshot(filename, user_id, chat_id):
                    deleted_count += 1
                    logger.info(f"Successfully deleted screenshot: {filename}")
                else:
                    failed_count += 1
                    failed_files.append(filename)
                    logger.error(f"Failed to delete screenshot: {filename}")

                # Обновляем статус каждые 5 файлов
                if (deleted_count + failed_count) % 5 == 0:
                    await status_message.edit_text(
                        f"🗑 Удаление категории '{label}'...\n"
                        f"Обработано: {deleted_count + failed_count} из {len(screenshots)}\n"
                        f"✅ Успешно: {deleted_count}\n"
                        f"❌ Ошибок: {failed_count}"
                    )

            except Exception as e:
                failed_count += 1
                failed_files.append(filename)
                logger.error(f"Error deleting screenshot {filename}: {e}", exc_info=True)

        # Формируем детальный отчет
        result_text = [
            f"📊 Результаты удаления категории '{label}':",
            f"✅ Успешно удалено: {deleted_count}",
            f"❌ Ошибок: {failed_count}"
        ]

        if failed_files:
            result_text.append("\nФайлы с ошибками:")
            for file in failed_files[:5]:  # Показываем только первые 5 файлов
                result_text.append(f"- {file}")
            if len(failed_files) > 5:
                result_text.append(f"...и еще {len(failed_files) - 5} файлов")

        keyboard = [
            [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
        ]

        await status_message.edit_text(
            "\n".join(result_text),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

        logger.info(f"Category deletion completed. Success: {deleted_count}, Failed: {failed_count}")

    except Exception as e:
        logger.error(f"Error in confirm delete category: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при удалении категории")
        # В случае ошибки возвращаемся в архив
        try:
            await handle_view_archive(callback)
        except Exception as e2:
            logger.error(f"Error returning to archive: {e2}", exc_info=True)

@router.callback_query(F.data == "view_by_date")
async def handle_view_by_date(callback: CallbackQuery):
    """Handle showing screenshots by date"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        screenshots = screenshot_storage.get_all_screenshots(user_id, chat_id)

        if not screenshots:
            await callback.message.edit_text(
                "Архив пуст. Скриншоты будут появляться по расписанию.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
                ])
            )
            return

        dates = set()
        for screenshot in screenshots:
            date = screenshot["timestamp"].split()[0]
            dates.add(date)

        keyboard = []
        for date in sorted(dates, reverse=True):
            date_screenshots = screenshot_storage.get_screenshots_by_date(date, user_id, chat_id)
            keyboard.append([InlineKeyboardButton(
                text=f"📅 {date} ({len(date_screenshots)})",
                callback_data=f"date_{date}"
            )])

        keyboard.append([
            InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")
        ])

        await callback.message.edit_text(
            "📅 Архив скриншотов по датам\nВыберите дату:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
    except Exception as e:
        logger.error(f"Error in view by date handler: {e}", exc_info=True)
        await callback.message.edit_text(
            "❌ Произошла ошибка при загрузке архива",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
            ])
        )

@router.callback_query(F.data.startswith("select_"))
async def handle_screenshot_selection(callback: CallbackQuery):
    """Handle screenshot selection for multiple deletion"""
    try:
        user_id = callback.from_user.id
        filename = callback.data.replace("select_", "")
        user_key = f"user_{user_id}"

        if filename in selected_screenshots[user_key]:
            selected_screenshots[user_key].remove(filename)
            await callback.answer("❌ Скриншот убран из выбранных")
        else:
            selected_screenshots[user_key].add(filename)
            await callback.answer("✅ Скриншот выбран")

        # Обновляем сообщение с обновленным статусом выбора
        await update_screenshot_message(callback.message, filename, user_id)

    except Exception as e:
        logger.error(f"Error in screenshot selection: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при выборе скриншота")

async def update_screenshot_message(message: Message, filename: str, user_id: int):
    """Update message with selection status"""
    try:
        user_key = f"user_{user_id}"
        is_selected = filename in selected_screenshots[user_key]

        keyboard = [
            [
                InlineKeyboardButton(
                    text="✅ Выбран" if is_selected else "☑️ Выбрать",
                    callback_data=f"select_{filename}"
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"delete_{filename}"
                )
            ],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="view_archive")]
        ]

        if len(selected_screenshots[user_key]) > 0:
            keyboard.insert(0, [
                InlineKeyboardButton(
                    text=f"🗑 Удалить выбранные ({len(selected_screenshots[user_key])})",
                    callback_data="delete_selected"
                )
            ])

        await message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
    except Exception as e:
        logger.error(f"Error updating screenshot message: {e}", exc_info=True)

@router.callback_query(F.data == "delete_selected")
async def handle_delete_selected(callback: CallbackQuery):
    """Handle deletion of multiple selected screenshots"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        user_key = f"user_{user_id}"

        if not selected_screenshots[user_key]:
            await callback.answer("❌ Нет выбранных скриншотов")
            return

        # Запрашиваем подтверждение
        keyboard = [
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data="confirm_delete_selected"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="cancel_delete_selected"
                )
            ]
        ]

        await callback.message.edit_text(
            f"🗑 Удалить выбранные скриншоты ({len(selected_screenshots[user_key])})?\n"
            "Это действие нельзя отменить.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error in delete selected handler: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")

@router.callback_query(F.data == "confirm_delete_selected")
async def handle_confirm_delete_selected(callback: CallbackQuery):
    """Handle confirmation of multiple screenshot deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        user_key = f"user_{user_id}"

        if not selected_screenshots[user_key]:
            await callback.answer("❌ Нет выбранных скриншотов")
            return

        deleted_count = 0
        failed_count = 0

        for filename in selected_screenshots[user_key]:
            if screenshot_storage.delete_screenshot(filename, user_id, chat_id):
                deleted_count += 1
            else:
                failed_count += 1

        # Очищаем выбранные скриншоты
        selected_screenshots[user_key].clear()

        # Показываем результат
        result_text = (
            f"✅ Успешно удалено: {deleted_count}\n"
            f"❌ Ошибок: {failed_count}"
        )

        keyboard = [
            [InlineKeyboardButton(text="🔙 Вернуться в архив", callback_data="view_archive")]
        ]

        await callback.message.edit_text(
            result_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error in confirm delete selected: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при удалении")

@router.callback_query(F.data == "cancel_delete_selected")
async def handle_cancel_delete_selected(callback: CallbackQuery):
    """Handle cancellation of multiple screenshot deletion"""
    try:
        user_id = callback.from_user.id
        user_key = f"user_{user_id}"

        # Очищаем выбранные скриншоты
        selected_screenshots[user_key].clear()

        await callback.answer("✅ Удаление отменено")
        # Возвращаемся в архив
        await handle_view_archive(callback)

    except Exception as e:
        logger.error(f"Error in cancel delete selected: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")

@router.callback_query(F.data.startswith("delete_category_"))
async def handle_delete_category(callback: CallbackQuery):
    """Handle deletion of all screenshots in a category"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        label = callback.data.replace("delete_category_", "")

        # Запрашиваем подтверждение
        keyboard = [
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"confirm_delete_category_{label}"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"label_{label}"
                )
            ]
        ]

        await callback.message.edit_text(
            f"⚠️ Вы уверены, что хотите удалить ВСЕ скриншоты из категории \"{label}\"?\n"
            "Это действие нельзя отменить.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error in delete category handler: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")

@router.callback_query(F.data.startswith("confirm_delete_category_"))
async def handle_confirm_delete_category(callback: CallbackQuery):
    """Handle confirmation of category deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        label = callback.data.replace("confirm_delete_category_", "")

        logger.info(f"Starting deletion of category '{label}' for user {user_id} in chat {chat_id}")

        screenshots = screenshot_storage.get_screenshots_by_label(label, user_id, chat_id)

        if not screenshots:
            logger.warning(f"No screenshots found in category '{label}'")
            await callback.answer("❌ Нет скриншотов для удаления")
            # Возвращаемся в архив
            await handle_view_archive(callback)
            return

        logger.info(f"Found {len(screenshots)} screenshots to delete in category '{label}'")

        deleted_count = 0
        failed_count = 0
        failed_files = []

        # Process deletion
        status_message = await callback.message.edit_text(
            f"🗑 Удаление категории '{label}'...\n"
            f"Всего файлов: {len(screenshots)}\n"
            "⏳ Пожалуйста, подождите..."
        )

        for screenshot in screenshots:
            try:
                # Получаем именно имя файла из пути
                filepath = screenshot["filepath"]
                filename = os.path.basename(filepath)
                logger.info(f"Attempting to delete screenshot: {filename} from path: {filepath}")

                if screenshot_storage.delete_screenshot(filename, user_id, chat_id):
                    deleted_count += 1
                    logger.info(f"Successfully deleted screenshot: {filename}")
                else:
                    failed_count += 1
                    failed_files.append(filename)
                    logger.error(f"Failed to delete screenshot: {filename}")

                # Обновляем статус каждые 5 файлов
                if (deleted_count + failed_count) % 5 == 0:
                    await status_message.edit_text(
                        f"🗑 Удаление категории '{label}'...\n"
                        f"Обработано: {deleted_count + failed_count} из {len(screenshots)}\n"
                        f"✅ Успешно: {deleted_count}\n"
                        f"❌ Ошибок: {failed_count}"
                    )

            except Exception as e:
                failed_count += 1
                failed_files.append(filename)
                logger.error(f"Error deleting screenshot {filename}: {e}", exc_info=True)

        # Формируем детальный отчет
        result_text = [
            f"📊 Результаты удаления категории '{label}':",
            f"✅ Успешно удалено: {deleted_count}",
            f"❌ Ошибок: {failed_count}"
        ]

        if failed_files:
            result_text.append("\nФайлы с ошибками:")
            for file in failed_files[:5]:  # Показываем только первые 5 файлов
                result_text.append(f"- {file}")
            if len(failed_files) > 5:
                result_text.append(f"...и еще {len(failed_files) - 5} файлов")

        keyboard = [
            [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
        ]

        await status_message.edit_text(
            "\n".join(result_text),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

        logger.info(f"Category deletion completed. Success: {deleted_count}, Failed: {failed_count}")

    except Exception as e:
        logger.error(f"Error in confirm delete category: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при удалении категории")
        # В случае ошибки возвращаемся в архив
        try:
            await handle_view_archive(callback)
        except Exception as e2:
            logger.error(f"Error returning to archive: {e2}", exc_info=True)

@router.callback_query(F.data == "view_stats")
async def handle_view_stats(callback: CallbackQuery):
    """Handle showing screenshot statistics"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id

        # Получаем все скриншоты пользователя
        all_screenshots = screenshot_storage.get_all_screenshots(user_id, chat_id)

        # Получаем статистику за текущий месяц
        monthly_stats = screenshot_stats.get_monthly_stats(all_screenshots)

        # Группируем скриншоты по меткам для подсчета
        labels = screenshot_storage.get_all_labels(user_id, chat_id)
        label_counts = {}
        for label in labels:
            label_screenshots = screenshot_storage.get_screenshots_by_label(label, user_id, chat_id)
            label_counts[label] = len(label_screenshots)

        # Формируем текст статистики с улучшенным форматированием
        stats_text = (
            "📊 Статистика скриншотов\n\n"
            f"📈 Всего скриншотов: {len(all_screenshots)}\n"
            f"🗓 В этом месяце: {monthly_stats['total_this_month']}\n"
            f"💫 Доступно: {monthly_stats['remaining_limit']} из 100\n"
            f"📊 Использовано: {monthly_stats['usage_percent']:.1f}%\n\n"
            "📁 По категориям:\n"
        )

        # Добавляем emoji для разных категорий
        category_emoji = {
            "Ежедневный отчет": "📆",
            "Начало месяца": "🆕",
            "Середина месяца": "📍",
            "Конец месяца": "🏁",
            "Сохранено вручную": "💾"
        }

        for label, count in label_counts.items():
            emoji = category_emoji.get(label, "📝")
            stats_text += f"{emoji} {label}: {count}\n"

        keyboard = [
            [
                InlineKeyboardButton(text="🔍 Фильтр по периоду", callback_data="filter_period"),
                InlineKeyboardButton(text="📂 Архив", callback_data="view_archive")
            ],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")]
        ]

        await callback.message.edit_text(
            stats_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error showing statistics: {e}")
        await callback.message.edit_text(
            "Произошла ошибка при загрузке статистики",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="view_archive")]
            ])
        )

@router.callback_query(F.data == "filter_period")
async def handle_filter_period(callback: CallbackQuery):
    """Handle period filter selection"""
    try:
        keyboard = [
            [InlineKeyboardButton(text="📅 Последняя неделя", callback_data="period_week")],
            [InlineKeyboardButton(text="📅 Последний месяц", callback_data="period_month")],
            [InlineKeyboardButton(text="📅 Последние 3 месяца", callback_data="period_3months")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="view_stats")]
        ]

        await callback.message.edit_text(
            "📊 Фильтрация по периоду\n\n"
            "Выберите период для просмотра скриншотов:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error showing period filter: {e}")
        await callback.message.edit_text("Произошла ошибка при загрузке фильтров")

@router.callback_query(F.data.startswith("period_"))
async def handle_period_selection(callback: CallbackQuery):
    """Handle specific period selection"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        period = callback.data.replace("period_", "")

        # Определяем даты периода
        end_date = datetime.now(pytz.UTC)
        period_names = {
            "week": "неделю",
            "month": "месяц",
            "3months": "3 месяца"
        }

        if period == "week":
            start_date = end_date - timedelta(days=7)
        elif period == "month":
            start_date = end_date - timedelta(days=30)
        elif period == "3months":
            start_date = end_date - timedelta(days=90)

        # Получаем все скриншоты и фильтруем по периоду
        all_screenshots = screenshot_storage.get_all_screenshots(user_id, chat_id)
        filtered_screenshots = screenshot_stats.filter_by_period(
            all_screenshots,
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d")
        )

        if not filtered_screenshots:
            await callback.message.edit_text(
                f"📭 За последний {period_names[period]} скриншотов не найдено",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="filter_period")]
                ])
            )
            return

        # Группируем по датам
        dates = set()
        for screenshot in filtered_screenshots:
            date = screenshot["timestamp"].split()[0]
            dates.add(date)

        keyboard = []
        for date in sorted(dates, reverse=True):
            day = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
            count = len([s for s in filtered_screenshots if s["timestamp"].startswith(date)])
            keyboard.append([
                InlineKeyboardButton(
                    text=f"📅 {day} ({count})",
                    callback_data=f"date_{date}"
                )
            ])

        keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="filter_period")])

        await callback.message.edit_text(
            f"📊 Скриншоты за {period_names[period]}:\n"
            f"Всего найдено: {len(filtered_screenshots)}\n\n"
            "Выберите дату для просмотра:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error handling period selection: {e}")
        await callback.message.edit_text("Произошла ошибка при фильтрации")

# Добавляем новые обработчики
@router.callback_query(F.data.startswith("select_"))
async def handle_screenshot_selection(callback: CallbackQuery):
    """Handle screenshot selection for multiple deletion"""
    try:
        user_id = callback.from_user.id
        filename = callback.data.replace("select_", "")
        user_key = f"user_{user_id}"

        if filename in selected_screenshots[user_key]:
            selected_screenshots[user_key].remove(filename)
            await callback.answer("❌ Скриншот убран из выбранных")
        else:
            selected_screenshots[user_key].add(filename)
            await callback.answer("✅ Скриншот выбран")

        # Обновляем сообщение с обновленным статусом выбора
        await update_screenshot_message(callback.message, filename, user_id)

    except Exception as e:
        logger.error(f"Error in screenshot selection: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при выборе скриншота")

async def update_screenshot_message(message: Message, filename: str, user_id: int):
    """Update message with selection status"""
    try:
        user_key = f"user_{user_id}"
        is_selected = filename in selected_screenshots[user_key]

        keyboard = [
            [
                InlineKeyboardButton(
                    text="✅ Выбран" if is_selected else "☑️ Выбрать",
                    callback_data=f"select_{filename}"
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"delete_{filename}"
                )
            ],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="view_archive")]
        ]

        if len(selected_screenshots[user_key]) > 0:
            keyboard.insert(0, [
                InlineKeyboardButton(
                    text=f"🗑 Удалить выбранные ({len(selected_screenshots[user_key])})",
                    callback_data="delete_selected"
                )
            ])

        await message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
    except Exception as e:
        logger.error(f"Error updating screenshot message: {e}", exc_info=True)

@router.callback_query(F.data == "delete_selected")
async def handle_delete_selected(callback: CallbackQuery):
    """Handle deletion of multiple selected screenshots"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        user_key = f"user_{user_id}"

        if not selected_screenshots[user_key]:
            await callback.answer("❌ Нет выбранных скриншотов")
            return

        # Запрашиваем подтверждение
        keyboard = [
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data="confirm_delete_selected"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="cancel_delete_selected"
                )
            ]
        ]

        await callback.message.edit_text(
            f"🗑 Удалить выбранные скриншоты ({len(selected_screenshots[user_key])})?\n"
            "Это действие нельзя отменить.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error in delete selected handler: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")

@router.callback_query(F.data == "confirm_delete_selected")
async def handle_confirm_delete_selected(callback: CallbackQuery):
    """Handle confirmation of multiple screenshot deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        user_key = f"user_{user_id}"

        if not selected_screenshots[user_key]:
            await callback.answer("❌ Нет выбранных скриншотов")
            return

        deleted_count = 0
        failed_count = 0

        for filename in selected_screenshots[user_key]:
            if screenshot_storage.delete_screenshot(filename, user_id, chat_id):
                deleted_count += 1
            else:
                failed_count += 1

        # Очищаем выбранные скриншоты
        selected_screenshots[user_key].clear()

        # Показываем результат
        result_text = (
            f"✅ Успешно удалено: {deleted_count}\n"
            f"❌ Ошибок: {failed_count}"
        )

        keyboard = [
            [InlineKeyboardButton(text="🔙 Вернуться в архив", callback_data="view_archive")]
        ]

        await callback.message.edit_text(
            result_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error in confirm delete selected: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при удалении")

@router.callback_query(F.data == "cancel_delete_selected")
async def handle_cancel_delete_selected(callback: CallbackQuery):
    """Handle cancellation of multiple screenshot deletion"""
    try:
        user_id = callback.from_user.id
        user_key = f"user_{user_id}"

        # Очищаем выбранные скриншоты
        selected_screenshots[user_key].clear()

        await callback.answer("✅ Удаление отменено")
        # Возвращаемся в архив
        await handle_view_archive(callback)

    except Exception as e:
        logger.error(f"Error in cancel delete selected: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")

@router.callback_query(F.data.startswith("delete_category_"))
async def handle_delete_category(callback: CallbackQuery):
    """Handle deletion of all screenshots in a category"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        label = callback.data.replace("delete_category_", "")

        # Запрашиваем подтверждение
        keyboard = [
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"confirm_delete_category_{label}"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"label_{label}"
                )
            ]
        ]

        await callback.message.edit_text(
            f"⚠️ Вы уверены, что хотите удалить ВСЕ скриншоты из категории \"{label}\"?\n"
            "Это действие нельзя отменить.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error in delete category handler: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")

@router.callback_query(F.data.startswith("confirm_delete_category_"))
async def handle_confirm_delete_category(callback: CallbackQuery):
    """Handle confirmation of category deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        label = callback.data.replace("confirm_delete_category_", "")

        logger.info(f"Starting deletion of category '{label}' for user {user_id} in chat {chat_id}")

        screenshots = screenshot_storage.get_screenshots_by_label(label, user_id, chat_id)

        if not screenshots:
            logger.warning(f"No screenshots found in category '{label}'")
            await callback.answer("❌ Нет скриншотов для удаления")
            # Возвращаемся в архив
            await handle_view_archive(callback)
            return

        logger.info(f"Found {len(screenshots)} screenshots to delete in category '{label}'")

        deleted_count = 0
        failed_count = 0
        failed_files = []

        # Process deletion
        status_message = await callback.message.edit_text(
            f"🗑 Удаление категории '{label}'...\n"
            f"Всего файлов: {len(screenshots)}\n"
            "⏳ Пожалуйста, подождите..."
        )

        for screenshot in screenshots:
            try:
                # Получаем именно имя файла из пути
                filepath = screenshot["filepath"]
                filename = os.path.basename(filepath)
                logger.info(f"Attempting to delete screenshot: {filename} from path: {filepath}")

                if screenshot_storage.delete_screenshot(filename, user_id, chat_id):
                    deleted_count += 1
                    logger.info(f"Successfully deleted screenshot: {filename}")
                else:
                    failed_count += 1
                    failed_files.append(filename)
                    logger.error(f"Failed to delete screenshot: {filename}")

                # Обновляем статус каждые 5 файлов
                if (deleted_count + failed_count) % 5 == 0:
                    await status_message.edit_text(
                        f"🗑 Удаление категории '{label}'...\n"
                        f"Обработано: {deleted_count + failed_count} из {len(screenshots)}\n"
                        f"✅ Успешно: {deleted_count}\n"
                        f"❌ Ошибок: {failed_count}"
                    )

            except Exception as e:
                failed_count += 1
                failed_files.append(filename)
                logger.error(f"Error deleting screenshot {filename}: {e}", exc_info=True)

        # Формируем детальный отчет
        result_text = [
            f"📊 Результаты удаления категории '{label}':",
            f"✅ Успешно удалено: {deleted_count}",
            f"❌ Ошибок: {failed_count}"
        ]

        if failed_files:
            result_text.append("\nФайлы с ошибками:")
            for file in failed_files[:5]:  # Показываем только первые 5 файлов
                result_text.append(f"- {file}")
            if len(failed_files) > 5:
                result_text.append(f"...и еще {len(failed_files) - 5} файлов")

        keyboard = [
            [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
        ]

        await status_message.edit_text(
            "\n".join(result_text),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

        logger.info(f"Category deletion completed. Success: {deleted_count}, Failed: {failed_count}")

    except Exception as e:
        logger.error(f"Error in confirm delete category: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при удалении категории")
        # В случае ошибки возвращаемся в архив
        try:
            await handle_view_archive(callback)
        except Exception as e2:
            logger.error(f"Error returning to archive: {e2}", exc_info=True)

@router.callback_query(F.data == "view_stats")
async def handle_view_stats(callback: CallbackQuery):
    """Handle showing screenshot statistics"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id

        # Получаем все скриншоты пользователя
        all_screenshots = screenshot_storage.get_all_screenshots(user_id, chat_id)

        # Получаем статистику за текущий месяц
        monthly_stats = screenshot_stats.get_monthly_stats(all_screenshots)

        # Группируем скриншоты по меткам для подсчета
        labels = screenshot_storage.get_all_labels(user_id, chat_id)
        label_counts = {}
        for label in labels:
            label_screenshots = screenshot_storage.get_screenshots_by_label(label, user_id, chat_id)
            label_counts[label] = len(label_screenshots)

        # Формируем текст статистики с улучшенным форматированием
        stats_text = (
            "📊 Статистика скриншотов\n\n"
            f"📈 Всего скриншотов: {len(all_screenshots)}\n"
            f"🗓 В этом месяце: {monthly_stats['total_this_month']}\n"
            f"💫 Доступно: {monthly_stats['remaining_limit']} из 100\n"
            f"📊 Использовано: {monthly_stats['usage_percent']:.1f}%\n\n"
            "📁 По категориям:\n"
        )

        # Добавляем emoji для разных категорий
        category_emoji = {
            "Ежедневный отчет": "📆",
            "Начало месяца": "🆕",
            "Середина месяца": "📍",
            "Конец месяца": "🏁",
            "Сохранено вручную": "💾"
        }

        for label, count in label_counts.items():
            emoji = category_emoji.get(label, "📝")
            stats_text += f"{emoji} {label}: {count}\n"

        keyboard = [
            [
                InlineKeyboardButton(text="🔍 Фильтр по периоду", callback_data="filter_period"),
                InlineKeyboardButton(text="📂 Архив", callback_data="view_archive")
            ],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")]
        ]

        await callback.message.edit_text(
            stats_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error showing statistics: {e}")
        await callback.message.edit_text(
            "Произошла ошибка при загрузке статистики",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="view_archive")]
            ])
        )

@router.callback_query(F.data == "filter_period")
async def handle_filter_period(callback: CallbackQuery):
    """Handle period filter selection"""
    try:
        keyboard = [
            [InlineKeyboardButton(text="📅 Последняя неделя", callback_data="period_week")],
            [InlineKeyboardButton(text="📅 Последний месяц", callback_data="period_month")],
            [InlineKeyboardButton(text="📅 Последние 3 месяца", callback_data="period_3months")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="view_stats")]
        ]

        await callback.message.edit_text(
            "📊 Фильтрация по периоду\n\n"
            "Выберите период для просмотра скриншотов:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error showing period filter: {e}")
        await callback.message.edit_text("Произошла ошибка при загрузке фильтров")

@router.callback_query(F.data.startswith("period_"))
async def handle_period_selection(callback: CallbackQuery):
    """Handle specific period selection"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        period = callback.data.replace("period_", "")

        # Определяем даты периода
        end_date = datetime.now(pytz.UTC)
        period_names = {
            "week": "неделю",
            "month": "месяц",
            "3months": "3 месяца"
        }

        if period == "week":
            start_date = end_date - timedelta(days=7)
        elif period == "month":
            start_date = end_date - timedelta(days=30)
        elif period == "3months":
            start_date = end_date - timedelta(days=90)

        # Получаем все скриншоты и фильтруем по периоду
        all_screenshots = screenshot_storage.get_all_screenshots(user_id, chat_id)
        filtered_screenshots = screenshot_stats.filter_by_period(
            all_screenshots,
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d")
        )

        if not filtered_screenshots:
            await callback.message.edit_text(
                f"📭 За последний {period_names[period]} скриншотов не найдено",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="filter_period")]
                ])
            )
            return

        # Группируем по датам
        dates = set()
        for screenshot in filtered_screenshots:
            date = screenshot["timestamp"].split()[0]
            dates.add(date)

        keyboard = []
        for date in sorted(dates, reverse=True):
            day = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
            count = len([s for s in filtered_screenshots if s["timestamp"].startswith(date)])
            keyboard.append([
                InlineKeyboardButton(
                    text=f"📅 {day} ({count})",
                    callback_data=f"date_{date}"
                )
            ])

        keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="filter_period")])

        await callback.message.edit_text(
            f"📊 Скриншоты за {period_names[period]}:\n"
            f"Всего найдено: {len(filtered_screenshots)}\n\n"
            "Выберите дату для просмотра:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error handling period selection: {e}")
        await callback.message.edit_text("Произошла ошибка при фильтрации")

@router.callback_query(F.data.startswith("select_"))
async def handle_screenshot_selection(callback: CallbackQuery):
    """Handle screenshot selection for multiple deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        filename = callback.data.replace("select_", "")
        user_key = f"user_{user_id}"

        if filename in selected_screenshots[user_key]:
            selected_screenshots[user_key].remove(filename)
            await callback.answer("❌ Скриншот убран из выбранных")
        else:
            selected_screenshots[user_key].add(filename)
            await callback.answer("✅ Скриншот добавлен к выбранным")

        # Обновляем интерфейс
        await update_screenshot_message(callback.message, user_id, chat_id)

    except Exception as e:
        logger.error(f"Error in screenshot selection: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")

async def update_screenshot_message(message: Message, user_id: int, chat_id: int):
    """Update message with selected screenshots"""
    try:
        user_key = f"user_{user_id}"
        current_label = None

        # Находим текущую метку из сообщения
        if "Категория:" in message.text:
            current_label = message.text.split("Категория:")[1].split("\n")[0].strip()
            screenshots = screenshot_storage.get_screenshots_by_label(current_label, user_id, chat_id)
        else:
            return

        keyboard = []
        
        # Добавляем кнопки действий, если есть выбранные скриншоты
        if selected_screenshots[user_key]:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"🗑 Удалить выбранные ({len(selected_screenshots[user_key])})",
                    callback_data="delete_selected"
                )
            ])

        # Добавляем кнопку для удаления всей категории
        keyboard.append([
            InlineKeyboardButton(
                text=f"🗑 Удалить все ({len(screenshots)})",
                callback_data=f"delete_category_{current_label}"
            )
        ])

        # Добавляем кнопки для каждого скриншота
        for screenshot in screenshots:
            filename = os.path.basename(screenshot['filepath'])
            is_selected = filename in selected_screenshots[user_key]
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{screenshot['timestamp']} {'✅' if is_selected else ''}",
                    callback_data=f"select_{filename}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")
        ])

        await message.edit_text(
            f"📁 Категория: {current_label}\n"
            "Выберите скриншоты для удаления:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error updating screenshot message: {e}", exc_info=True)

@router.callback_query(F.data == "delete_selected")
async def handle_delete_selected(callback: CallbackQuery):
    """Handle deletion of selected screenshots"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        user_key = f"user_{user_id}"

        if not selected_screenshots[user_key]:
            await callback.answer("❌ Нет выбранных скриншотов")
            return

        # Запрашиваем подтверждение
        keyboard = [
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data="confirm_delete_selected"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="cancel_delete_selected"
                )
            ]
        ]

        await callback.message.edit_text(
            f"⚠️ Вы уверены, что хотите удалить {len(selected_screenshots[user_key])} выбранных скриншотов?\n"
            "Это действие нельзя отменить.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error in delete selected handler: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")

@router.callback_query(F.data == "confirm_delete_selected")
async def handle_confirm_delete_selected(callback: CallbackQuery):
    """Handle confirmation of selected screenshots deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        user_key = f"user_{user_id}"

        # Показываем статус удаления
        status_message = await callback.message.edit_text(
            "🗑 Удаление выбранных скриншотов...\n"
            f"Всего файлов: {len(selected_screenshots[user_key])}\n"
            "⏳ Пожалуйста, подождите..."
        )

        deleted_count = 0
        failed_count = 0
        failed_files = []

        for filename in selected_screenshots[user_key]:
            try:
                logger.info(f"Attempting to delete selected screenshot: {filename}")
                if screenshot_storage.delete_screenshot(filename, user_id, chat_id):
                    deleted_count += 1
                    logger.info(f"Successfully deleted selected screenshot: {filename}")
                else:
                    failed_count += 1
                    failed_files.append(filename)
                    logger.error(f"Failed to delete selected screenshot: {filename}")

                # Обновляем статус каждые 5 файлов
                if (deleted_count + failed_count) % 5 == 0:
                    await status_message.edit_text(
                        "🗑 Удаление выбранных скриншотов...\n"
                        f"Обработано: {deleted_count + failed_count} из {len(selected_screenshots[user_key])}\n"
                        f"✅ Успешно: {deleted_count}\n"
                        f"❌ Ошибок: {failed_count}"
                    )

            except Exception as e:
                failed_count += 1
                failed_files.append(filename)
                logger.error(f"Error deleting selected screenshot {filename}: {e}", exc_info=True)

        # Очищаем выбранные скриншоты
        selected_screenshots[user_key].clear()

        # Формируем отчет
        result_text = [
            "📊 Результаты удаления:",
            f"✅ Успешно удалено: {deleted_count}",
            f"❌ Ошибок: {failed_count}"
        ]

        if failed_files:
            result_text.append("\nФайлы с ошибками:")
            for file in failed_files[:5]:
                result_text.append(f"- {file}")
            if len(failed_files) > 5:
                result_text.append(f"...и еще {len(failed_files) - 5} файлов")

        keyboard = [
            [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
        ]

        await status_message.edit_text(
            "\n".join(result_text),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"Error in confirm delete selected: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при удалении")
        try:
            await handle_view_archive(callback)
        except Exception as e2:
            logger.error(f"Error returning to archive: {e2}", exc_info=True)

@router.callback_query(F.data == "cancel_delete_selected")
async def handle_cancel_delete_selected(callback: CallbackQuery):
    """Handle cancellation of selected screenshots deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        # Возвращаемся к просмотру выбранных скриншотов
        await update_screenshot_message(callback.message, user_id, chat_id)
        await callback.answer("❌ Удаление отменено")
    except Exception as e:
        logger.error(f"Error in cancel delete selected: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")

def register_handlers(dp: Dispatcher):
    """Register all handlers"""
    logger.info("Starting handlers registration")
    try:
        dp.include_router(router)
        logger.info("Successfully registered main router")
    except Exception as e:
        logger.error(f"Error registering handlers: {e}", exc_info=True)
        raise

@router.callback_query(F.data.startswith("select_"))
async def handle_screenshot_selection(callback: CallbackQuery):
    """Handle screenshot selection for multiple deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        filename = callback.data.replace("select_", "")
        user_key = f"user_{user_id}"
        
        logger.info(f"[SELECTION] Processing selection for file: {filename}")
        logger.info(f"[SELECTION] User key: {user_key}")
        logger.info(f"[SELECTION] Current selected files: {selected_screenshots[user_key]}")

        if filename in selected_screenshots[user_key]:
            selected_screenshots[user_key].remove(filename)
            logger.info(f"[SELECTION] Removed {filename} from selection")
            await callback.answer("❌ Скриншот убран из выбранных")
        else:
            selected_screenshots[user_key].add(filename)
            logger.info(f"[SELECTION] Added {filename} to selection")
            await callback.answer("✅ Скриншот добавлен к выбранным")

        # Обновляем интерфейс
        await update_screenshot_message(callback.message, user_id, chat_id)

    except Exception as e:
        logger.error(f"[SELECTION] Error in screenshot selection: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")

async def update_screenshot_message(message: Message, user_id: int, chat_id: int):
    """Update message with selected screenshots"""
    try:
        logger.info("[UPDATE_MESSAGE] Starting message update")
        user_key = f"user_{user_id}"
        
        if not message or not message.text:
            logger.error("[UPDATE_MESSAGE] Message or message text is None")
            return

        current_label = None
        if "Категория:" in message.text:
            current_label = message.text.split("Категория:")[1].split("\n")[0].strip()
            logger.info(f"[UPDATE_MESSAGE] Found category: {current_label}")
            screenshots = screenshot_storage.get_screenshots_by_label(current_label, user_id, chat_id)
            logger.info(f"[UPDATE_MESSAGE] Found {len(screenshots)} screenshots")
        else:
            logger.error("[UPDATE_MESSAGE] Cannot find category in message text")
            return

        keyboard = []
        
        # Добавляем кнопки действий, если есть выбранные скриншоты
        if selected_screenshots[user_key]:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"🗑 Удалить выбранные ({len(selected_screenshots[user_key])})",
                    callback_data="delete_selected"
                )
            ])
            logger.info(f"[UPDATE_MESSAGE] Added delete selected button for {len(selected_screenshots[user_key])} files")

        # Добавляем кнопку для удаления всей категории
        keyboard.append([
            InlineKeyboardButton(
                text=f"🗑 Удалить все ({len(screenshots)})",
                callback_data=f"delete_category_{current_label}"
            )
        ])
        logger.info(f"[UPDATE_MESSAGE] Added delete all button for {len(screenshots)} files")

        # Добавляем кнопки для каждого скриншота
        for screenshot in screenshots:
            filename = os.path.basename(screenshot['filepath'])
            is_selected = filename in selected_screenshots[user_key]
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{screenshot['timestamp']} {'✅' if is_selected else ''}",
                    callback_data=f"select_{filename}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")
        ])

        logger.info("[UPDATE_MESSAGE] Updating message with new keyboard")
        await message.edit_text(
            f"📁 Категория: {current_label}\n"
            "Выберите скриншоты для удаления:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        logger.info("[UPDATE_MESSAGE] Message updated successfully")

    except Exception as e:
        logger.error(f"[UPDATE_MESSAGE] Error updating screenshot message: {e}", exc_info=True)

@router.callback_query(F.data.startswith("delete_category_"))
async def handle_delete_category(callback: CallbackQuery):
    """Handle deletion of all screenshots in a category"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        label = callback.data.replace("delete_category_", "")
        
        logger.info(f"[DELETE_CATEGORY] Starting deletion process for category '{label}'")
        logger.info(f"[DELETE_CATEGORY] User ID: {user_id}, Chat ID: {chat_id}")
        
        # Get all screenshots in the category
        screenshots = screenshot_storage.get_screenshots_by_label(label, user_id, chat_id)
        logger.info(f"[DELETE_CATEGORY] Found {len(screenshots)} screenshots to delete")
        
        for screenshot in screenshots:
            logger.info(f"[DELETE_CATEGORY] Found screenshot: {screenshot['filepath']} with label: {screenshot['label']}")

        if not screenshots:
            logger.warning(f"[DELETE_CATEGORY] No screenshots found in category '{label}'")
            await callback.answer("❌ Нет скриншотов для удаления")
            return

        # Request confirmation
        keyboard = [
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"confirm_delete_category_{label}"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"label_{label}"
                )
            ]
        ]

        await callback.message.edit_text(
            f"⚠️ Вы уверены, что хотите удалить ВСЕ скриншоты из категории \"{label}\"?\n"
            f"Всего скриншотов: {len(screenshots)}\n"
            "Это действие нельзя отменить.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

    except Exception as e:
        logger.error(f"[DELETE_CATEGORY] Error in delete category handler: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка")
        try:
            await handle_view_archive(callback)
        except Exception as e2:
            logger.error(f"[DELETE_CATEGORY] Error returning to archive: {e2}", exc_info=True)

@router.callback_query(F.data.startswith("confirm_delete_category_"))
async def handle_confirm_delete_category(callback: CallbackQuery):
    """Handle confirmation of category deletion"""
    try:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        label = callback.data.replace("confirm_delete_category_", "")

        logger.info(f"[CONFIRM_DELETE] Starting deletion of category '{label}' for user {user_id} in chat {chat_id}")

        screenshots = screenshot_storage.get_screenshots_by_label(label, user_id, chat_id)
        logger.info(f"[CONFIRM_DELETE] Found {len(screenshots)} screenshots to delete")
        for screenshot in screenshots:
            logger.info(f"[CONFIRM_DELETE] Will delete: {screenshot['filepath']} with label: {screenshot['label']}")

        if not screenshots:
            logger.warning(f"[CONFIRM_DELETE] No screenshots found in category '{label}'")
            await callback.answer("❌ Нет доступных скриншотов для удаления")
            await handle_view_archive(callback)
            return

        # Show deletion status
        status_message = await callback.message.edit_text(
            "🗑 Удаление скриншотов...\n"
            f"Всего файлов: {len(screenshots)}\n"
            "⏳ Пожалуйста, подождите..."
        )

        deleted_count = 0
        failed_count = 0
        failed_files = []

        for screenshot in screenshots:
            try:
                # Use only the filename from the full path
                filename = os.path.basename(screenshot["filepath"])
                logger.info(f"[CONFIRM_DELETE] Attempting to delete: {filename}")

                if screenshot_storage.delete_screenshot(filename, user_id, chat_id):
                    deleted_count += 1
                    logger.info(f"[CONFIRM_DELETE] Successfully deleted: {filename}")
                else:
                    failed_count += 1
                    failed_files.append(filename)
                    logger.error(f"[CONFIRM_DELETE] Failed to delete: {filename}")

                # Update status every 5 files
                if (deleted_count + failed_count) % 5 == 0:
                    await status_message.edit_text(
                        "🗑 Удаление скриншотов...\n"
                        f"Обработано: {deleted_count + failed_count} из {len(screenshots)}\n"
                        f"✅ Успешно: {deleted_count}\n"
                        f"❌ Ошибок: {failed_count}"
                    )

            except Exception as e:
                failed_count += 1
                if 'filename' in locals():
                    failed_files.append(filename)
                logger.error(f"[CONFIRM_DELETE] Error deleting file: {e}", exc_info=True)

        # Generate report
        result_text = [
            "📊 Результаты удаления:",
            f"✅ Успешно удалено: {deleted_count}",
            f"❌ Ошибок: {failed_count}"
        ]

        if failed_files:
            result_text.append("\nФайлы с ошибками:")
            for file in failed_files[:5]:
                result_text.append(f"- {file}")
            if len(failed_files) > 5:
                result_text.append(f"...и еще {len(failed_files) - 5} файлов")

        keyboard = [
            [InlineKeyboardButton(text="🔙 К архиву", callback_data="view_archive")]
        ]

        await status_message.edit_text(
            "\n".join(result_text),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

        logger.info(f"[CONFIRM_DELETE] Category deletion completed. Success: {deleted_count}, Failed: {failed_count}")

    except Exception as e:
        logger.error(f"[CONFIRM_DELETE] Error in confirm delete category: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при удалении категории")
        try:
            await handle_view_archive(callback)
        except Exception as e2:
            logger.error(f"[CONFIRM_DELETE] Error returning to archive: {e2}", exc_info=True)