#!/usr/bin/env python3
"""
Telegram Verification Bot v2.0 - ПОЛНАЯ ВЕРСИЯ
Все настройки зашиты в код, из .env только BOT_TOKEN и OWNER_ID
"""

import os
import re
import asyncio
import logging
import sqlite3
import json
import random
import string
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Set, Tuple
from dataclasses import dataclass, field
from contextlib import contextmanager
from pathlib import Path

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile, ChatMemberUpdated,
    ChatPermissions, BotCommand, BotCommandScopeDefault
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from dotenv import load_dotenv
import aioschedule

# ============================================================
# Загрузка .env (только для BOT_TOKEN и OWNER_ID)
# ============================================================

load_dotenv()

# ============================================================
# ВСЕ НАСТРОЙКИ ЗДЕСЬ (зашиты в код)
# ============================================================

# Настройки бота (ОБЯЗАТЕЛЬНО из .env)
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", 0))

# Настройки базы данных (ЗАШИТЫ В КОД)
DATABASE_NAME = "database.db"

# Настройки отчетов (ЗАШИТЫ В КОД)
REPORT_TIME = "23:59"
TIMEZONE = "Europe/Moscow"

# Настройки верификации (ЗАШИТЫ В КОД)
VERIFY_TIMEOUT = 120  # секунд
MAX_ATTEMPTS = 3  # попытки
DELETE_DELAY = 60  # секунд - удаление сообщений бота
MAX_MESSAGES_PER_MINUTE = 20

# Настройки логирования (ЗАШИТЫ В КОД)
LOG_LEVEL = "INFO"

# Проверка обязательных переменных
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не задан в .env!")
if not OWNER_ID:
    raise ValueError("❌ OWNER_ID не задан в .env!")

# ============================================================
# Настройка логирования
# ============================================================

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================
# ТЕКСТЫ
# ============================================================

WELCOME_TEXT = """
🌟 Добро пожаловать в Вейп-Барахолку Краснодара, {user_mention}! 🎉

📋 Правила чата:
🚫 Запрещено:
• ❌ Не вейп-тематика
• ❌ Оскорбления и флуд
• ❌ Спам и реклама

⚠️ Внимание!
При скаме: @callumom 
Администрация не отвечает за сделки.

🏪 Лучшие вейп-шопы:
• 🔥 Mix Vape: https://t.me/mixvape1

💫 Приятного общения!
"""

VERIFICATION_START = """
🔐 **ВЕРИФИКАЦИЯ**

👤 {user_mention}

Для подтверждения, что вы не робот, решите пример:

❓ **{num1} × {num2} = ?**

⏳ У вас {timeout} секунд и {attempts} попытки.

💡 Выберите правильный ответ на кнопках ниже!
"""

VERIFICATION_FAILED = """
❌ **Неправильно!**

Осталось попыток: {remaining}

Попробуйте снова:
"""

VERIFICATION_BLOCKED = """
⛔ **Доступ запрещен!**

{user_mention}, вы не прошли верификацию.

Попробуйте зайти позже.
"""

VERIFICATION_REMINDER = """
🔐 **Вы на верификации!**

{user_mention}, ответьте на вопрос выше.
"""

# ============================================================
# База данных
# ============================================================

class Database:
    """Работа с SQLite"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_tables()
        self._cache_words = None
        self._cache_whitelist = None
    
    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _init_tables(self):
        """Создание всех таблиц при первом запуске"""
        with self.connect() as conn:
            cursor = conn.cursor()
            
            # Группы
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS groups (
                    group_id INTEGER PRIMARY KEY,
                    title TEXT,
                    verified_only BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Верифицированные пользователи
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS verified_users (
                    user_id INTEGER,
                    group_id INTEGER,
                    username TEXT,
                    first_name TEXT,
                    verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, group_id)
                )
            ''')
            
            # Забаненные пользователи
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS banned_users (
                    user_id INTEGER,
                    group_id INTEGER,
                    reason TEXT,
                    banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, group_id)
                )
            ''')
            
            # Запрещенные слова
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS forbidden_words (
                    word TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Белый список слов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS whitelist_words (
                    word TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Белый список пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS whitelist_users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Статистика
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS statistics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER,
                    date TEXT,
                    messages INTEGER DEFAULT 0,
                    new_members INTEGER DEFAULT 0,
                    verifications_passed INTEGER DEFAULT 0,
                    verifications_failed INTEGER DEFAULT 0,
                    messages_deleted INTEGER DEFAULT 0,
                    users_restricted INTEGER DEFAULT 0,
                    active_users INTEGER DEFAULT 0,
                    UNIQUE(group_id, date)
                )
            ''')
            
            # Логи
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT,
                    group_id INTEGER,
                    user_id INTEGER,
                    username TEXT,
                    message TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Настройки
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Добавляем настройки по умолчанию
            cursor.execute('''
                INSERT OR IGNORE INTO settings (key, value)
                VALUES 
                    ('verification_enabled', '1'),
                    ('verification_attempts', '3'),
                    ('verification_timeout', '120'),
                    ('spam_check_enabled', '1'),
                    ('delete_delay', '60'),
                    ('max_messages_per_minute', '20')
            ''')
            
            conn.commit()
            logger.info("✅ Таблицы созданы/проверены")
    
    # ==================== Кэширование ====================
    
    def get_forbidden_words(self) -> Set[str]:
        """Получение кэша запрещенных слов"""
        if self._cache_words is None:
            self._cache_words = self._load_forbidden_words()
        return self._cache_words
    
    def _load_forbidden_words(self) -> Set[str]:
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT word FROM forbidden_words')
            return {row[0] for row in cursor.fetchall()}
    
    def add_forbidden_word(self, word: str):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO forbidden_words (word) VALUES (?)', (word.lower(),))
            conn.commit()
        self._cache_words = None
    
    def remove_forbidden_word(self, word: str):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM forbidden_words WHERE word = ?', (word.lower(),))
            conn.commit()
        self._cache_words = None
    
    def get_whitelist_users(self) -> Set[int]:
        if self._cache_whitelist is None:
            self._cache_whitelist = self._load_whitelist_users()
        return self._cache_whitelist
    
    def _load_whitelist_users(self) -> Set[int]:
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM whitelist_users')
            return {row[0] for row in cursor.fetchall()}
    
    def add_whitelist_user(self, user_id: int):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO whitelist_users (user_id) VALUES (?)', (user_id,))
            conn.commit()
        self._cache_whitelist = None
    
    def remove_whitelist_user(self, user_id: int):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM whitelist_users WHERE user_id = ?', (user_id,))
            conn.commit()
        self._cache_whitelist = None
    
    # ==================== Верификация ====================
    
    def is_verified(self, user_id: int, group_id: int) -> bool:
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT 1 FROM verified_users WHERE user_id = ? AND group_id = ?',
                (user_id, group_id)
            )
            return cursor.fetchone() is not None
    
    def mark_verified(self, user_id: int, group_id: int, username: str = None, first_name: str = None):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO verified_users (user_id, group_id, username, first_name)
                VALUES (?, ?, ?, ?)
            ''', (user_id, group_id, username, first_name))
            conn.commit()
    
    def mark_old_users_as_verified(self, group_id: int, user_ids: List[int]):
        """Помечает существующих пользователей как верифицированных"""
        if not user_ids:
            return
        with self.connect() as conn:
            cursor = conn.cursor()
            for user_id in user_ids:
                cursor.execute('''
                    INSERT OR IGNORE INTO verified_users (user_id, group_id, username, first_name)
                    SELECT ?, ?, username, first_name FROM users WHERE user_id = ?
                ''', (user_id, group_id, user_id))
            conn.commit()
    
    # ==================== Бан ====================
    
    def is_banned(self, user_id: int, group_id: int) -> bool:
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT 1 FROM banned_users WHERE user_id = ? AND group_id = ?',
                (user_id, group_id)
            )
            return cursor.fetchone() is not None
    
    def ban_user(self, user_id: int, group_id: int, reason: str = ""):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO banned_users (user_id, group_id, reason)
                VALUES (?, ?, ?)
            ''', (user_id, group_id, reason))
            conn.commit()
    
    def unban_user(self, user_id: int, group_id: int):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM banned_users WHERE user_id = ? AND group_id = ?', (user_id, group_id))
            conn.commit()
    
    # ==================== Статистика ====================
    
    def update_stats(self, group_id: int, field: str, value: int = 1):
        date = datetime.now().strftime("%Y-%m-%d")
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                INSERT INTO statistics (group_id, date, {field})
                VALUES (?, ?, ?)
                ON CONFLICT(group_id, date) DO UPDATE SET
                    {field} = {field} + ?
            ''', (group_id, date, value, value))
            conn.commit()
    
    def get_stats(self, group_id: int, days: int = 30) -> List[dict]:
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM statistics
                WHERE group_id = ? AND date >= date('now', ?)
                ORDER BY date DESC
            ''', (group_id, f'-{days} days'))
            return [dict(row) for row in cursor.fetchall()]
    
    # ==================== Логи ====================
    
    def add_log(self, event_type: str, group_id: int, user_id: int = None,
                username: str = None, message: str = None):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO logs (event_type, group_id, user_id, username, message)
                VALUES (?, ?, ?, ?, ?)
            ''', (event_type, group_id, user_id, username, message))
            conn.commit()
    
    # ==================== Настройки ====================
    
    def get_setting(self, key: str, default: str = None) -> str:
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
            row = cursor.fetchone()
            return row[0] if row else default
    
    def set_setting(self, key: str, value: str):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (key, value))
            conn.commit()

# ============================================================
# Состояния FSM
# ============================================================

class AdminStates(StatesGroup):
    """Состояния для админ-панели"""
    waiting_for_word = State()
    waiting_for_word_remove = State()
    waiting_for_word_search = State()
    waiting_for_whitelist_add = State()
    waiting_for_whitelist_remove = State()
    waiting_for_settings = State()
    waiting_for_import = State()

# ============================================================
# Утилиты
# ============================================================

class TextNormalizer:
    """Нормализация текста"""
    
    @staticmethod
    def normalize(text: str) -> str:
        if not text:
            return ""
        
        text = text.lower()
        
        # Удаляем все эмодзи
        emoji_pattern = re.compile("["
            u"\U0001F600-\U0001F64F"
            u"\U0001F300-\U0001F5FF"
            u"\U0001F680-\U0001F6FF"
            u"\U0001F1E0-\U0001F1FF"
            u"\U00002702-\U000027B0"
            u"\U000024C2-\U0001F251"
            u"\U0001F900-\U0001F9FF"
            u"\U0001FA70-\U0001FAFF"
            "]+", flags=re.UNICODE)
        text = emoji_pattern.sub(r'', text)
        
        # Заменяем кириллицу на латиницу
        replacements = {
            'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd',
            'е': 'e', 'ё': 'e', 'ж': 'zh', 'з': 'z', 'и': 'i',
            'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n',
            'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't',
            'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch',
            'ш': 'sh', 'щ': 'sh', 'ъ': '', 'ы': 'y', 'ь': '',
            'э': 'e', 'ю': 'yu', 'я': 'ya'
        }
        for cyrillic, latin in replacements.items():
            text = text.replace(cyrillic, latin)
        
        text = re.sub(r'[\s\n\r\t]+', '', text)
        text = re.sub(r'[^\w]', '', text)
        
        return text
    
    @staticmethod
    def normalize_original(text: str) -> str:
        """Нормализация оригинального текста (без замены кириллицы)"""
        if not text:
            return ""
        text = text.lower()
        text = re.sub(r'[\s\n\r\t]+', '', text)
        text = re.sub(r'[^\wа-яё]', '', text)
        return text
    
    @staticmethod
    def check_forbidden(text: str, forbidden_words: Set[str]) -> Tuple[bool, str]:
        """Двойная проверка текста"""
        if not text:
            return False, ""
        
        # Проверка очищенного текста
        clean = TextNormalizer.normalize(text)
        for word in forbidden_words:
            if word in clean:
                return True, word
        
        # Проверка оригинального текста
        original = TextNormalizer.normalize_original(text)
        for word in forbidden_words:
            if word in original:
                return True, word
        
        return False, ""

# ============================================================
# Клавиатуры
# ============================================================

class Keyboards:
    """Все клавиатуры бота"""
    
    @staticmethod
    def admin_main() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📝 Слова")],
                [KeyboardButton(text="➕ Добавить слово"), KeyboardButton(text="➖ Удалить слово")],
                [KeyboardButton(text="🔍 Поиск слова"), KeyboardButton(text="📋 Список слов")],
                [KeyboardButton(text="📥 Импорт слов"), KeyboardButton(text="📤 Экспорт слов")],
                [KeyboardButton(text="🛡️ Белый список"), KeyboardButton(text="📜 Логи")],
                [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="📊 Отправить отчет")]
            ],
            resize_keyboard=True
        )
    
    @staticmethod
    def cancel() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
            ]
        )
    
    @staticmethod
    def verification(options: List[Tuple[str, int]]) -> InlineKeyboardMarkup:
        buttons = []
        for label, value in options:
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"verify_{value}")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

# ============================================================
# Основной бот
# ============================================================

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
db = Database(DATABASE_NAME)

# ============================================================
# Глобальные переменные
# ============================================================

verification_data = {}  # user_id: {chat_id, answer, attempts, timeout, message_id}
message_queue = []  # Для удаления сообщений

# ============================================================
# Функция удаления сообщений
# ============================================================

async def delete_message_after_delay(chat_id: int, message_id: int, delay: int = DELETE_DELAY):
    """Удалить сообщение через указанную задержку"""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.debug(f"Не удалось удалить сообщение {message_id}: {e}")

async def send_and_delete(chat_id: int, text: str, reply_markup=None, delay: int = DELETE_DELAY) -> Message:
    """Отправить сообщение и удалить через delay секунд"""
    try:
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        asyncio.create_task(delete_message_after_delay(chat_id, msg.message_id, delay))
        return msg
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        return None

# ============================================================
# Middleware - проверка прав
# ============================================================

async def check_user_permissions(chat_id: int, user_id: int) -> bool:
    """Проверка прав пользователя"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in [ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR]:
            return True
        if user_id == OWNER_ID:
            return True
        if user_id in db.get_whitelist_users():
            return True
        return False
    except:
        return False

# ============================================================
# Проверка сообщений
# ============================================================

async def check_message_for_spam(message: Message) -> bool:
    """Проверка сообщения на запрещенные слова"""
    
    if not message.chat.type in ['group', 'supergroup']:
        return False
    
    # Получаем текст
    text = message.text or message.caption or ""
    if not text:
        return False
    
    # Получаем запрещенные слова
    forbidden_words = db.get_forbidden_words()
    if not forbidden_words:
        return False
    
    # Проверяем
    found, word = TextNormalizer.check_forbidden(text, forbidden_words)
    return found

# ============================================================
# Обработка спама
# ============================================================

async def handle_spam(message: Message):
    """Обработка спама"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Удаляем сообщение
    try:
        await message.delete()
    except:
        pass
    
    # Ограничиваем пользователя
    try:
        await bot.restrict_chat_member(
            chat_id, user_id,
            permissions=ChatPermissions(can_send_messages=False)
        )
    except:
        pass
    
    # Баним в БД
    db.ban_user(user_id, chat_id, "Спам")
    
    # Логируем
    db.add_log(
        'spam', chat_id, user_id,
        message.from_user.username or "",
        f"Найдено слово в: {message.text or message.caption or 'медиа'}"
    )
    
    # Статистика
    db.update_stats(chat_id, 'messages_deleted')
    db.update_stats(chat_id, 'users_restricted')
    
    # Уведомление владельцу
    await bot.send_message(
        OWNER_ID,
        f"🚫 **Забанен спамер!**\n\n"
        f"👤 {message.from_user.full_name}\n"
        f"🆔 ID: `{user_id}`\n"
        f"🔗 @{message.from_user.username or 'отсутствует'}\n"
        f"💬 Группа: {message.chat.title or chat_id}\n"
        f"📝 Текст: {message.text or message.caption or 'медиа'}\n"
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
    )
    
    # Сообщение в группе (удаляется через 60 сек)
    await send_and_delete(
        chat_id,
        f"🚫 {message.from_user.first_name}, вы забанены за спам!"
    )

# ============================================================
# Верификация
# ============================================================

async def start_verification(chat_id: int, user_id: int, user, is_retry: bool = False):
    """Начать верификацию для нового пользователя"""
    
    # Проверяем, не верифицирован ли уже
    if db.is_verified(user_id, chat_id):
        return
    
    # Проверяем права
    if await check_user_permissions(chat_id, user_id):
        db.mark_verified(user_id, chat_id, user.username, user.first_name)
        return
    
    # Ограничиваем права
    try:
        await bot.restrict_chat_member(
            chat_id, user_id,
            permissions=ChatPermissions(can_send_messages=False)
        )
    except:
        pass
    
    # Если уже есть верификация - удаляем старую
    if user_id in verification_data:
        old_data = verification_data[user_id]
        if 'timeout' in old_data:
            old_data['timeout'].cancel()
        if 'message_id' in old_data:
            try:
                await bot.delete_message(chat_id, old_data['message_id'])
            except:
                pass
        del verification_data[user_id]
    
    # Генерируем пример
    num1 = random.randint(1, 9)
    num2 = random.randint(1, 9)
    answer = num1 * num2
    
    # Создаем варианты ответов
    options = [answer]
    while len(options) < 3:
        wrong = answer + random.randint(-5, 5)
        if wrong != answer and wrong > 0 and wrong not in options:
            options.append(wrong)
    random.shuffle(options)
    
    # Создаем клавиатуру
    keyboard = Keyboards.verification([
        (str(opt), opt) for opt in options
    ])
    
    # Отправляем сообщение
    user_mention = f"@{user.username}" if user.username else user.first_name
    
    if is_retry:
        text = VERIFICATION_REMINDER.format(user_mention=user_mention) + "\n\n" + VERIFICATION_START.format(
            user_mention=user_mention,
            num1=num1,
            num2=num2,
            timeout=VERIFY_TIMEOUT,
            attempts=MAX_ATTEMPTS
        )
    else:
        text = VERIFICATION_START.format(
            user_mention=user_mention,
            num1=num1,
            num2=num2,
            timeout=VERIFY_TIMEOUT,
            attempts=MAX_ATTEMPTS
        )
    
    msg = await bot.send_message(chat_id, text, reply_markup=keyboard)
    
    # Запланировать удаление сообщения через 60 секунд
    asyncio.create_task(delete_message_after_delay(chat_id, msg.message_id, DELETE_DELAY))
    
    # Сохраняем данные
    timeout_task = asyncio.create_task(verification_timeout(chat_id, user_id))
    verification_data[user_id] = {
        'chat_id': chat_id,
        'answer': answer,
        'attempts': 0,
        'timeout': timeout_task,
        'user': user,
        'message_id': msg.message_id
    }
    
    # Статистика (только если не повторная)
    if not is_retry:
        db.update_stats(chat_id, 'new_members')
    
    # Логируем
    db.add_log(
        'verification_started', chat_id, user_id,
        user.username or "", f"{user.full_name} начал верификацию"
    )

async def verification_timeout(chat_id: int, user_id: int):
    """Таймаут верификации"""
    await asyncio.sleep(VERIFY_TIMEOUT)
    
    if user_id in verification_data:
        data = verification_data[user_id]
        user = data.get('user')
        
        # Удаляем сообщение с верификацией
        if 'message_id' in data:
            try:
                await bot.delete_message(chat_id, data['message_id'])
            except:
                pass
        
        # Баним
        db.ban_user(user_id, chat_id, "Не прошел верификацию (таймаут)")
        db.update_stats(chat_id, 'verifications_failed')
        
        # Логируем
        db.add_log(
            'verification_timeout', chat_id, user_id,
            user.username if user else "", "Таймаут верификации"
        )
        
        # Сообщение (удаляется через 60 сек)
        await send_and_delete(
            chat_id,
            f"⏰ {user.first_name if user else ''}, время вышло!\nПопробуйте зайти позже."
        )
        
        del verification_data[user_id]

@dp.callback_query(F.data.startswith("verify_"))
async def verify_callback(callback: CallbackQuery):
    """Обработка ответа на верификацию"""
    
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    
    # Проверяем, есть ли пользователь в верификации
    if user_id not in verification_data:
        await callback.answer("❌ Верификация не активна")
        await callback.message.delete()
        return
    
    data = verification_data[user_id]
    
    # Проверяем ответ
    answer = int(callback.data.split("_")[1])
    
    if answer == data['answer']:
        # ✅ ПРАВИЛЬНЫЙ ОТВЕТ
        await callback.answer("✅ Правильно!")
        
        # Удаляем сообщение с верификацией
        try:
            await callback.message.delete()
        except:
            pass
        
        # Снимаем ограничения
        try:
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
        except:
            pass
        
        # Отмечаем как верифицированного
        user = data.get('user') or callback.from_user
        db.mark_verified(
            user_id, chat_id,
            callback.from_user.username or user.username,
            callback.from_user.first_name or user.first_name
        )
        
        # Статистика
        db.update_stats(chat_id, 'verifications_passed')
        
        # Логируем
        db.add_log(
            'verified', chat_id, user_id,
            callback.from_user.username or "",
            f"{callback.from_user.full_name} прошел верификацию"
        )
        
        # Удаляем из верификации
        if 'timeout' in data:
            data['timeout'].cancel()
        del verification_data[user_id]
        
        # ✅ ПРИВЕТСТВЕННОЕ СООБЩЕНИЕ (удаляется через 60 сек)
        user_mention = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.first_name
        welcome_text = WELCOME_TEXT.format(user_mention=user_mention)
        
        await send_and_delete(chat_id, welcome_text)
        
    else:
        # ❌ НЕПРАВИЛЬНЫЙ ОТВЕТ
        data['attempts'] += 1
        remaining = MAX_ATTEMPTS - data['attempts']
        
        if remaining <= 0:
            # Попытки исчерпаны
            await callback.answer("❌ Попытки исчерпаны!")
            
            # Удаляем сообщение
            try:
                await callback.message.delete()
            except:
                pass
            
            # Баним
            db.ban_user(user_id, chat_id, "Не прошел верификацию")
            db.update_stats(chat_id, 'verifications_failed')
            
            # Логируем
            db.add_log(
                'verification_failed', chat_id, user_id,
                callback.from_user.username or "",
                f"{callback.from_user.full_name} не прошел верификацию"
            )
            
            if 'timeout' in data:
                data['timeout'].cancel()
            del verification_data[user_id]
            
            # Сообщение (удаляется через 60 сек)
            user_mention = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.first_name
            await send_and_delete(
                chat_id,
                VERIFICATION_BLOCKED.format(user_mention=user_mention)
            )
        else:
            # Генерируем новый пример
            await callback.answer(f"❌ Неправильно! Осталось {remaining} попыток")
            
            # Удаляем старое сообщение
            try:
                await callback.message.delete()
            except:
                pass
            
            num1 = random.randint(1, 9)
            num2 = random.randint(1, 9)
            answer = num1 * num2
            
            options = [answer]
            while len(options) < 3:
                wrong = answer + random.randint(-5, 5)
                if wrong != answer and wrong > 0 and wrong not in options:
                    options.append(wrong)
            random.shuffle(options)
            
            keyboard = Keyboards.verification([
                (str(opt), opt) for opt in options
            ])
            
            user_mention = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.first_name
            
            msg = await bot.send_message(
                chat_id,
                VERIFICATION_FAILED.format(remaining=remaining) +
                f"\n❓ **{num1} × {num2} = ?**\n\n"
                f"⏳ У вас {VERIFY_TIMEOUT} секунд",
                reply_markup=keyboard
            )
            
            # Запланировать удаление сообщения
            asyncio.create_task(delete_message_after_delay(chat_id, msg.message_id, DELETE_DELAY))
            
            # Обновляем ответ и сохраняем новый message_id
            data['answer'] = answer
            data['message_id'] = msg.message_id

# ============================================================
# Обработка новых участников
# ============================================================

@dp.chat_member()
async def chat_member_handler(update: ChatMemberUpdated):
    """Обработка входа новых участников"""
    
    if not update.new_chat_member:
        return
    
    user = update.new_chat_member.user
    chat_id = update.chat.id
    
    # Проверяем ботов
    if user.is_bot:
        return
    
    # Проверяем, не забанен ли
    if db.is_banned(user.id, chat_id):
        try:
            await bot.ban_chat_member(chat_id, user.id)
        except:
            pass
        return
    
    # Проверяем, верифицирован ли уже
    if db.is_verified(user.id, chat_id):
        logger.info(f"👤 Старый пользователь {user.id} зашел, верификация не нужна")
        return
    
    # Начинаем верификацию для новых пользователей
    logger.info(f"🆕 Новый пользователь {user.id} зашел, начинаем верификацию")
    await start_verification(chat_id, user.id, user, is_retry=False)

# ============================================================
# Обработка всех сообщений
# ============================================================

@dp.message(F.chat.type.in_({'group', 'supergroup'}))
async def group_message_handler(message: Message):
    """Обработка всех сообщений в группах"""
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Проверяем права
    if await check_user_permissions(chat_id, user_id):
        return
    
    # Проверяем бан
    if db.is_banned(user_id, chat_id):
        try:
            await message.delete()
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(can_send_messages=False)
            )
        except:
            pass
        return
    
    # Проверяем верификацию
    if not db.is_verified(user_id, chat_id):
        # Удаляем сообщение
        try:
            await message.delete()
        except:
            pass
        
        # Если пользователь уже на верификации - удаляем старую и отправляем новую
        if user_id in verification_data:
            # Удаляем старую верификацию
            old_data = verification_data[user_id]
            if 'message_id' in old_data:
                try:
                    await bot.delete_message(chat_id, old_data['message_id'])
                except:
                    pass
            if 'timeout' in old_data:
                old_data['timeout'].cancel()
            del verification_data[user_id]
        
        # Отправляем новую верификацию (всегда)
        await start_verification(chat_id, user_id, message.from_user, is_retry=True)
        return
    
    # ✅ ВЕРИФИЦИРОВАННЫЙ ПОЛЬЗОВАТЕЛЬ - проверяем на спам
    found = await check_message_for_spam(message)
    if found:
        await handle_spam(message)
        return
    
    # Обновляем статистику
    db.update_stats(chat_id, 'messages')

# ============================================================
# Команды пользователя
# ============================================================

@dp.message(Command("start"))
async def start_command(message: Message):
    """Команда start"""
    await send_and_delete(
        message.chat.id,
        "🤖 Привет! Я бот для защиты групп от спама.\n\n"
        "📌 Если вы администратор, используйте /admin для входа в панель."
    )

@dp.message(Command("admin"))
async def admin_command(message: Message):
    """Админ-панель"""
    
    if message.from_user.id != OWNER_ID:
        await send_and_delete(message.chat.id, "⛔ Доступ запрещен!")
        return
    
    await message.answer(
        "👋 Привет, владелец!\n\n"
        "📋 Выберите действие:",
        reply_markup=Keyboards.admin_main()
    )

# ============================================================
# Админ-панель (кнопки) - полный код
# ============================================================

@dp.message(lambda m: m.text == "📊 Статистика" and m.from_user.id == OWNER_ID)
async def admin_stats(message: Message):
    """Показать статистику"""
    
    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT group_id, title FROM groups')
        groups = cursor.fetchall()
    
    if not groups:
        await message.answer("📊 Нет данных о группах")
        return
    
    for group in groups:
        group_id = group['group_id']
        stats = db.get_stats(group_id, 30)
        
        if not stats:
            await message.answer(f"📊 Группа: {group['title'] or group_id}\nНет данных")
            continue
        
        total_messages = sum(s['messages'] for s in stats)
        total_new = sum(s['new_members'] for s in stats)
        total_verified = sum(s['verifications_passed'] for s in stats)
        total_failed = sum(s['verifications_failed'] for s in stats)
        total_deleted = sum(s['messages_deleted'] for s in stats)
        
        await message.answer(
            f"📊 **Группа:** {group['title'] or group_id}\n\n"
            f"📨 Сообщений: {total_messages}\n"
            f"👤 Новых: {total_new}\n"
            f"✅ Прошли верификацию: {total_verified}\n"
            f"❌ Не прошли: {total_failed}\n"
            f"🗑 Удалено: {total_deleted}\n"
            f"📅 За 30 дней"
        )

@dp.message(lambda m: m.text == "📝 Слова" and m.from_user.id == OWNER_ID)
async def admin_words(message: Message):
    """Показать статистику по словам"""
    words = db.get_forbidden_words()
    await message.answer(
        f"📝 **Слова в фильтре:** {len(words)}\n\n"
        f"Используйте кнопки для управления:"
    )

@dp.message(lambda m: m.text == "➕ Добавить слово" and m.from_user.id == OWNER_ID)
async def admin_add_word(message: Message, state: FSMContext):
    """Добавить слово"""
    await state.set_state(AdminStates.waiting_for_word)
    await message.answer(
        "📝 Отправьте слово для добавления в фильтр.\n\n"
        "Пример: `спам`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=Keyboards.cancel()
    )

@dp.message(AdminStates.waiting_for_word)
async def process_add_word(message: Message, state: FSMContext):
    """Обработка добавления слова"""
    word = message.text.lower().strip()
    if len(word) < 2:
        await message.answer("❌ Слово должно быть длиннее 1 символа")
        return
    
    db.add_forbidden_word(word)
    db.add_log('word_add', 0, message.from_user.id, message.from_user.username, word)
    
    await message.answer(f"✅ Слово '{word}' добавлено в фильтр!")
    await state.clear()

@dp.message(lambda m: m.text == "➖ Удалить слово" and m.from_user.id == OWNER_ID)
async def admin_remove_word(message: Message, state: FSMContext):
    """Удалить слово"""
    await state.set_state(AdminStates.waiting_for_word_remove)
    await message.answer(
        "📝 Отправьте слово для удаления из фильтра.\n\n"
        "Пример: `спам`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=Keyboards.cancel()
    )

@dp.message(AdminStates.waiting_for_word_remove)
async def process_remove_word(message: Message, state: FSMContext):
    """Обработка удаления слова"""
    word = message.text.lower().strip()
    db.remove_forbidden_word(word)
    db.add_log('word_remove', 0, message.from_user.id, message.from_user.username, word)
    
    await message.answer(f"✅ Слово '{word}' удалено из фильтра!")
    await state.clear()

@dp.message(lambda m: m.text == "🔍 Поиск слова" and m.from_user.id == OWNER_ID)
async def admin_search_word(message: Message, state: FSMContext):
    """Поиск слова"""
    await state.set_state(AdminStates.waiting_for_word_search)
    await message.answer(
        "🔍 Введите слово для поиска в фильтре:",
        reply_markup=Keyboards.cancel()
    )

@dp.message(AdminStates.waiting_for_word_search)
async def process_search_word(message: Message, state: FSMContext):
    """Обработка поиска слова"""
    word = message.text.lower().strip()
    words = db.get_forbidden_words()
    
    found = [w for w in words if word in w]
    
    if found:
        await message.answer(
            f"🔍 Найдено {len(found)} совпадений:\n\n" + "\n".join(f"• {w}" for w in found[:20])
        )
    else:
        await message.answer(f"❌ Слово '{word}' не найдено в фильтре")
    
    await state.clear()

@dp.message(lambda m: m.text == "📋 Список слов" and m.from_user.id == OWNER_ID)
async def admin_list_words(message: Message):
    """Список всех слов"""
    words = db.get_forbidden_words()
    
    if not words:
        await message.answer("📋 Список слов пуст")
        return
    
    chunks = [list(words[i:i+50]) for i in range(0, len(words), 50)]
    
    for i, chunk in enumerate(chunks, 1):
        await message.answer(
            f"📋 **Слова в фильтре (часть {i}/{len(chunks)})**\n\n"
            + "\n".join(f"• {w}" for w in chunk)
        )

@dp.message(lambda m: m.text == "📥 Импорт слов" and m.from_user.id == OWNER_ID)
async def admin_import_words(message: Message, state: FSMContext):
    """Импорт слов из файла"""
    await state.set_state(AdminStates.waiting_for_import)
    await message.answer(
        "📥 Отправьте текстовый файл (.txt) со словами.\n\n"
        "Каждое слово на новой строке.",
        reply_markup=Keyboards.cancel()
    )

@dp.message(AdminStates.waiting_for_import, F.document)
async def process_import_words(message: Message, state: FSMContext):
    """Обработка импорта слов"""
    document = message.document
    
    if not document.file_name.endswith('.txt'):
        await message.answer("❌ Отправьте файл в формате .txt")
        return
    
    try:
        file = await bot.get_file(document.file_id)
        file_bytes = await bot.download_file(file.file_path)
        content = file_bytes.decode('utf-8', errors='ignore')
        
        words = [w.strip().lower() for w in content.splitlines() if w.strip()]
        
        if not words:
            await message.answer("❌ Файл пуст")
            return
        
        added = 0
        for word in words:
            if len(word) >= 2:
                db.add_forbidden_word(word)
                added += 1
        
        db.add_log('word_import', 0, message.from_user.id, message.from_user.username, f"{added} слов")
        
        await message.answer(f"✅ Импортировано {added} слов из {len(words)}")
        
    except Exception as e:
        logger.error(f"Ошибка импорта: {e}")
        await message.answer(f"❌ Ошибка: {e}")
    
    await state.clear()

@dp.message(lambda m: m.text == "📤 Экспорт слов" and m.from_user.id == OWNER_ID)
async def admin_export_words(message: Message):
    """Экспорт слов в файл"""
    words = db.get_forbidden_words()
    
    if not words:
        await message.answer("📋 Список слов пуст")
        return
    
    content = "\n".join(sorted(words))
    file_path = "exported_words.txt"
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    await message.answer_document(
        FSInputFile(file_path),
        caption="📤 Экспорт слов в TXT"
    )
    
    os.remove(file_path)

@dp.message(lambda m: m.text == "🛡️ Белый список" and m.from_user.id == OWNER_ID)
async def admin_whitelist(message: Message):
    """Управление белым списком"""
    whitelist = db.get_whitelist_users()
    
    await message.answer(
        f"🛡️ **Белый список пользователей**\n\n"
        f"Всего: {len(whitelist)}\n\n"
        "Используйте команды:\n"
        "`/whitelist_add <id>` - добавить\n"
        "`/whitelist_remove <id>` - удалить\n"
        "`/whitelist_list` - список\n\n"
        "Слова в белом списке: /whitelist_words",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(Command("whitelist_add"))
async def whitelist_add(message: Message, command: CommandObject):
    """Добавить в белый список"""
    if message.from_user.id != OWNER_ID:
        return
    
    if not command.args:
        await message.answer("❌ Укажите ID: `/whitelist_add 123456`")
        return
    
    try:
        user_id = int(command.args)
        db.add_whitelist_user(user_id)
        await message.answer(f"✅ Пользователь {user_id} добавлен в белый список")
    except ValueError:
        await message.answer("❌ Неверный ID")

@dp.message(Command("whitelist_remove"))
async def whitelist_remove(message: Message, command: CommandObject):
    """Удалить из белого списка"""
    if message.from_user.id != OWNER_ID:
        return
    
    if not command.args:
        await message.answer("❌ Укажите ID: `/whitelist_remove 123456`")
        return
    
    try:
        user_id = int(command.args)
        db.remove_whitelist_user(user_id)
        await message.answer(f"✅ Пользователь {user_id} удален из белого списка")
    except ValueError:
        await message.answer("❌ Неверный ID")

@dp.message(Command("whitelist_list"))
async def whitelist_list(message: Message):
    """Список белого списка"""
    if message.from_user.id != OWNER_ID:
        return
    
    whitelist = db.get_whitelist_users()
    if whitelist:
        await message.answer(
            "🛡️ **Белый список пользователей:**\n\n" + 
            "\n".join(f"• {uid}" for uid in whitelist)
        )
    else:
        await message.answer("🛡️ Белый список пуст")

@dp.message(lambda m: m.text == "📜 Логи" and m.from_user.id == OWNER_ID)
async def admin_logs(message: Message):
    """Показать последние логи"""
    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM logs 
            ORDER BY timestamp DESC 
            LIMIT 20
        ''')
        logs = cursor.fetchall()
    
    if not logs:
        await message.answer("📜 Логов нет")
        return
    
    text = "📜 **Последние логи:**\n\n"
    for log in logs:
        text += f"• {log['timestamp']} | {log['event_type']}"
        if log['username']:
            text += f" | @{log['username']}"
        text += "\n"
    
    await message.answer(text[:4000])

@dp.message(lambda m: m.text == "⚙️ Настройки" and m.from_user.id == OWNER_ID)
async def admin_settings(message: Message):
    """Настройки"""
    settings = {
        'verification_enabled': db.get_setting('verification_enabled', '1'),
        'verification_attempts': db.get_setting('verification_attempts', '3'),
        'verification_timeout': db.get_setting('verification_timeout', '120'),
        'delete_delay': db.get_setting('delete_delay', '60'),
        'max_messages_per_minute': db.get_setting('max_messages_per_minute', '20'),
    }
    
    await message.answer(
        f"⚙️ **Настройки бота**\n\n"
        f"🔐 Верификация: {'✅ Вкл' if settings['verification_enabled'] == '1' else '❌ Выкл'}\n"
        f"🔄 Попыток: {settings['verification_attempts']}\n"
        f"⏱ Таймаут: {settings['verification_timeout']} сек\n"
        f"🗑 Удаление: {settings['delete_delay']} сек\n"
        f"📨 Лимит сообщений: {settings['max_messages_per_minute']}/мин\n\n"
        "Используйте команды:\n"
        "`/set_verify on/off`\n"
        "`/set_attempts <число>`\n"
        "`/set_timeout <сек>`\n"
        "`/set_delete_delay <сек>`\n"
        "`/set_message_limit <число>`",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(lambda m: m.text == "📊 Отправить отчет" and m.from_user.id == OWNER_ID)
async def admin_send_report(message: Message):
    """Отправить отчет"""
    await send_daily_report()
    await message.answer("✅ Отчет отправлен!")

# ============================================================
# Команды настроек
# ============================================================

@dp.message(Command("set_verify"))
async def set_verify(message: Message, command: CommandObject):
    """Включить/выключить верификацию"""
    if message.from_user.id != OWNER_ID:
        return
    
    if not command.args:
        await message.answer("❌ Используйте: /set_verify on/off")
        return
    
    value = '1' if command.args.lower() == 'on' else '0'
    db.set_setting('verification_enabled', value)
    await message.answer(f"✅ Верификация {'включена' if value == '1' else 'выключена'}")

@dp.message(Command("set_attempts"))
async def set_attempts(message: Message, command: CommandObject):
    """Установить количество попыток"""
    if message.from_user.id != OWNER_ID:
        return
    
    if not command.args:
        await message.answer("❌ Используйте: /set_attempts 3")
        return
    
    try:
        value = int(command.args)
        if value < 1 or value > 10:
            await message.answer("❌ Допустимо от 1 до 10")
            return
        db.set_setting('verification_attempts', str(value))
        await message.answer(f"✅ Попыток установлено: {value}")
    except ValueError:
        await message.answer("❌ Введите число")

@dp.message(Command("set_timeout"))
async def set_timeout(message: Message, command: CommandObject):
    """Установить таймаут"""
    if message.from_user.id != OWNER_ID:
        return
    
    if not command.args:
        await message.answer("❌ Используйте: /set_timeout 120")
        return
    
    try:
        value = int(command.args)
        if value < 30 or value > 600:
            await message.answer("❌ Допустимо от 30 до 600 секунд")
            return
        db.set_setting('verification_timeout', str(value))
        await message.answer(f"✅ Таймаут установлен: {value} сек")
    except ValueError:
        await message.answer("❌ Введите число")

@dp.message(Command("set_delete_delay"))
async def set_delete_delay(message: Message, command: CommandObject):
    """Установить задержку удаления"""
    if message.from_user.id != OWNER_ID:
        return
    
    if not command.args:
        await message.answer("❌ Используйте: /set_delete_delay 60")
        return
    
    try:
        value = int(command.args)
        if value < 5 or value > 300:
            await message.answer("❌ Допустимо от 5 до 300 секунд")
            return
        db.set_setting('delete_delay', str(value))
        await message.answer(f"✅ Задержка удаления: {value} сек")
    except ValueError:
        await message.answer("❌ Введите число")

@dp.message(Command("set_message_limit"))
async def set_message_limit(message: Message, command: CommandObject):
    """Установить лимит сообщений"""
    if message.from_user.id != OWNER_ID:
        return
    
    if not command.args:
        await message.answer("❌ Используйте: /set_message_limit 20")
        return
    
    try:
        value = int(command.args)
        if value < 5 or value > 100:
            await message.answer("❌ Допустимо от 5 до 100")
            return
        db.set_setting('max_messages_per_minute', str(value))
        await message.answer(f"✅ Лимит сообщений: {value}/мин")
    except ValueError:
        await message.answer("❌ Введите число")

# ============================================================
# Обработка отмены
# ============================================================

@dp.callback_query(lambda c: c.data == "cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext):
    """Отмена действия"""
    await state.clear()
    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer("✅ Действие отменено")

# ============================================================
# Ежедневный отчет
# ============================================================

async def send_daily_report():
    """Отправка ежедневного отчета"""
    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT group_id, title FROM groups')
        groups = cursor.fetchall()
    
    report = f"📊 **ЕЖЕДНЕВНЫЙ ОТЧЕТ**\n📅 {datetime.now().strftime('%d.%m.%Y')}\n\n"
    
    for group in groups:
        group_id = group['group_id']
        today = datetime.now().strftime("%Y-%m-%d")
        
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM statistics 
                WHERE group_id = ? AND date = ?
            ''', (group_id, today))
            stats = cursor.fetchone()
        
        if stats:
            report += f"**{group['title'] or group_id}**\n"
            report += f"├ 📨 Сообщений: {stats['messages']}\n"
            report += f"├ 👤 Новых: {stats['new_members']}\n"
            report += f"├ ✅ Прошли: {stats['verifications_passed']}\n"
            report += f"├ ❌ Не прошли: {stats['verifications_failed']}\n"
            report += f"├ 🗑 Удалено: {stats['messages_deleted']}\n"
            report += f"└ 🚫 Ограничено: {stats['users_restricted']}\n\n"
    
    try:
        await bot.send_message(OWNER_ID, report)
    except Exception as e:
        logger.error(f"Ошибка отправки отчета: {e}")

# ============================================================
# Инициализация групп при старте
# ============================================================

async def init_groups():
    """Инициализация групп при старте"""
    try:
        updates = await bot.get_updates(limit=100)
        for update in updates:
            if update.message and update.message.chat.type in ['group', 'supergroup']:
                chat = update.message.chat
                with db.connect() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT OR IGNORE INTO groups (group_id, title)
                        VALUES (?, ?)
                    ''', (chat.id, chat.title))
                    conn.commit()
                    
                    # Помечаем существующих участников как верифицированных
                    try:
                        members = await bot.get_chat_administrators(chat.id)
                        for member in members:
                            if not member.user.is_bot:
                                db.mark_verified(
                                    member.user.id, chat.id,
                                    member.user.username,
                                    member.user.first_name
                                )
                    except:
                        pass
                    
        logger.info("✅ Группы инициализированы")
    except Exception as e:
        logger.error(f"Ошибка инициализации групп: {e}")

# ============================================================
# Фоновая задача
# ============================================================

async def scheduler():
    """Планировщик задач"""
    while True:
        aioschedule.run_pending()
        await asyncio.sleep(60)

# ============================================================
# Запуск
# ============================================================

async def main():
    """Главная функция"""
    
    # Устанавливаем команды бота
    await bot.set_my_commands([
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="admin", description="Админ-панель"),
    ], scope=BotCommandScopeDefault())
    
    # Инициализируем группы
    await init_groups()
    
    # Настраиваем расписание
    try:
        report_hour, report_minute = map(int, REPORT_TIME.split(':'))
        aioschedule.every().day.at(f"{report_hour:02d}:{report_minute:02d}").do(
            lambda: asyncio.create_task(send_daily_report())
        )
    except:
        aioschedule.every().day.at("23:59").do(
            lambda: asyncio.create_task(send_daily_report())
        )
    
    # Запускаем планировщик
    asyncio.create_task(scheduler())
    
    logger.info("🚀 Бот запущен!")
    logger.info(f"🤖 @{await bot.get_me()}")
    logger.info("=" * 50)
    logger.info("🔐 Логика работы:")
    logger.info("  1. Старые пользователи - НЕ проходят верификацию")
    logger.info("  2. Новые пользователи - проходят верификацию с кнопками")
    logger.info("  3. После верификации - приветственный текст (удаляется через 60 сек)")
    logger.info("  4. Все сообщения бота удаляются через 60 секунд")
    logger.info("  5. При попытке написать - повторная верификация")
    logger.info("  6. Все пользователи проверяются на спам-слова")
    logger.info("  7. Админы и whitelist - исключения")
    logger.info("=" * 50)
    
    # Запускаем поллинг
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())