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

try:
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
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    print("📝 Установите зависимости: pip install aiogram python-dotenv aioschedule")
    exit(1)

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
# БАЗА ДАННЫХ
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
    
    def add_log(self, event_type: str, group_id: int, user_id: int = None,
                username: str = None, message: str = None):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO logs (event_type, group_id, user_id, username, message)
                VALUES (?, ?, ?, ?, ?)
            ''', (event_type, group_id, user_id, username, message))
            conn.commit()
    
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
# СОСТОЯНИЯ FSM
# ============================================================

class AdminStates(StatesGroup):
    waiting_for_word = State()
    waiting_for_word_remove = State()
    waiting_for_word_search = State()
    waiting_for_whitelist_add = State()
    waiting_for_whitelist_remove = State()
    waiting_for_settings = State()
    waiting_for_import = State()

# ============================================================
# УТИЛИТЫ
# ============================================================

class TextNormalizer:
    @staticmethod
    def normalize(text: str) -> str:
        if not text:
            return ""
        text = text.lower()
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
        if not text:
            return ""
        text = text.lower()
        text = re.sub(r'[\s\n\r\t]+', '', text)
        text = re.sub(r'[^\wа-яё]', '', text)
        return text
    
    @staticmethod
    def check_forbidden(text: str, forbidden_words: Set[str]) -> Tuple[bool, str]:
        if not text:
            return False, ""
        clean = TextNormalizer.normalize(text)
        for word in forbidden_words:
            if word in clean:
                return True, word
        original = TextNormalizer.normalize_original(text)
        for word in forbidden_words:
            if word in original:
                return True, word
        return False, ""

# ============================================================
# КЛАВИАТУРЫ
# ============================================================

class Keyboards:
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
# БОТ
# ============================================================

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
db = Database(DATABASE_NAME)

verification_data = {}

# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

async def delete_message_after_delay(chat_id: int, message_id: int, delay: int = DELETE_DELAY):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass

async def send_and_delete(chat_id: int, text: str, reply_markup=None, delay: int = DELETE_DELAY):
    try:
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        asyncio.create_task(delete_message_after_delay(chat_id, msg.message_id, delay))
        return msg
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        return None

async def check_user_permissions(chat_id: int, user_id: int) -> bool:
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
# ОБРАБОТЧИКИ
# ============================================================

@dp.chat_member()
async def chat_member_handler(update: ChatMemberUpdated):
    if not update.new_chat_member:
        return
    
    user = update.new_chat_member.user
    chat_id = update.chat.id
    
    if user.is_bot:
        return
    
    if db.is_banned(user.id, chat_id):
        try:
            await bot.ban_chat_member(chat_id, user.id)
        except:
            pass
        return
    
    if db.is_verified(user.id, chat_id):
        logger.info(f"👤 Старый пользователь {user.id} зашел")
        return
    
    logger.info(f"🆕 Новый пользователь {user.id} зашел")
    
    # Ограничиваем права
    try:
        await bot.restrict_chat_member(
            chat_id, user.id,
            permissions=ChatPermissions(can_send_messages=False)
        )
    except:
        pass
    
    # Генерируем пример
    num1 = random.randint(1, 9)
    num2 = random.randint(1, 9)
    answer = num1 * num2
    
    options = [answer]
    while len(options) < 3:
        wrong = answer + random.randint(-5, 5)
        if wrong != answer and wrong > 0 and wrong not in options:
            options.append(wrong)
    random.shuffle(options)
    
    keyboard = Keyboards.verification([(str(opt), opt) for opt in options])
    user_mention = f"@{user.username}" if user.username else user.first_name
    
    msg = await bot.send_message(
        chat_id,
        VERIFICATION_START.format(
            user_mention=user_mention,
            num1=num1,
            num2=num2,
            timeout=VERIFY_TIMEOUT,
            attempts=MAX_ATTEMPTS
        ),
        reply_markup=keyboard
    )
    
    asyncio.create_task(delete_message_after_delay(chat_id, msg.message_id, DELETE_DELAY))
    
    timeout_task = asyncio.create_task(verification_timeout(chat_id, user.id))
    verification_data[user.id] = {
        'chat_id': chat_id,
        'answer': answer,
        'attempts': 0,
        'timeout': timeout_task,
        'user': user,
        'message_id': msg.message_id
    }
    
    db.update_stats(chat_id, 'new_members')
    db.add_log('verification_started', chat_id, user.id, user.username or "", f"{user.full_name} начал верификацию")

async def verification_timeout(chat_id: int, user_id: int):
    await asyncio.sleep(VERIFY_TIMEOUT)
    
    if user_id in verification_data:
        data = verification_data[user_id]
        user = data.get('user')
        
        if 'message_id' in data:
            try:
                await bot.delete_message(chat_id, data['message_id'])
            except:
                pass
        
        db.ban_user(user_id, chat_id, "Не прошел верификацию (таймаут)")
        db.update_stats(chat_id, 'verifications_failed')
        db.add_log('verification_timeout', chat_id, user_id, user.username if user else "", "Таймаут верификации")
        
        await send_and_delete(chat_id, f"⏰ {user.first_name if user else ''}, время вышло!")
        del verification_data[user_id]

@dp.callback_query(F.data.startswith("verify_"))
async def verify_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    
    if user_id not in verification_data:
        await callback.answer("❌ Верификация не активна")
        await callback.message.delete()
        return
    
    data = verification_data[user_id]
    answer = int(callback.data.split("_")[1])
    
    if answer == data['answer']:
        await callback.answer("✅ Правильно!")
        await callback.message.delete()
        
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
        
        user = data.get('user') or callback.from_user
        db.mark_verified(user_id, chat_id, callback.from_user.username or user.username, callback.from_user.first_name or user.first_name)
        db.update_stats(chat_id, 'verifications_passed')
        db.add_log('verified', chat_id, user_id, callback.from_user.username or "", f"{callback.from_user.full_name} прошел верификацию")
        
        if 'timeout' in data:
            data['timeout'].cancel()
        del verification_data[user_id]
        
        user_mention = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.first_name
        await send_and_delete(chat_id, WELCOME_TEXT.format(user_mention=user_mention))
        
    else:
        data['attempts'] += 1
        remaining = MAX_ATTEMPTS - data['attempts']
        
        if remaining <= 0:
            await callback.answer("❌ Попытки исчерпаны!")
            await callback.message.delete()
            
            db.ban_user(user_id, chat_id, "Не прошел верификацию")
            db.update_stats(chat_id, 'verifications_failed')
            db.add_log('verification_failed', chat_id, user_id, callback.from_user.username or "", f"{callback.from_user.full_name} не прошел верификацию")
            
            if 'timeout' in data:
                data['timeout'].cancel()
            del verification_data[user_id]
            
            user_mention = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.first_name
            await send_and_delete(chat_id, VERIFICATION_BLOCKED.format(user_mention=user_mention))
        else:
            await callback.answer(f"❌ Неправильно! Осталось {remaining} попыток")
            await callback.message.delete()
            
            num1 = random.randint(1, 9)
            num2 = random.randint(1, 9)
            answer = num1 * num2
            
            options = [answer]
            while len(options) < 3:
                wrong = answer + random.randint(-5, 5)
                if wrong != answer and wrong > 0 and wrong not in options:
                    options.append(wrong)
            random.shuffle(options)
            
            keyboard = Keyboards.verification([(str(opt), opt) for opt in options])
            user_mention = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.first_name
            
            msg = await bot.send_message(
                chat_id,
                VERIFICATION_FAILED.format(remaining=remaining) +
                f"\n❓ **{num1} × {num2} = ?**\n\n"
                f"⏳ У вас {VERIFY_TIMEOUT} секунд",
                reply_markup=keyboard
            )
            
            asyncio.create_task(delete_message_after_delay(chat_id, msg.message_id, DELETE_DELAY))
            data['answer'] = answer
            data['message_id'] = msg.message_id

@dp.message(F.chat.type.in_({'group', 'supergroup'}))
async def group_message_handler(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if await check_user_permissions(chat_id, user_id):
        return
    
    if db.is_banned(user_id, chat_id):
        try:
            await message.delete()
            await bot.restrict_chat_member(chat_id, user_id, permissions=ChatPermissions(can_send_messages=False))
        except:
            pass
        return
    
    if not db.is_verified(user_id, chat_id):
        try:
            await message.delete()
        except:
            pass
        
        # Отправляем новую верификацию
        if user_id in verification_data:
            old_data = verification_data[user_id]
            if 'message_id' in old_data:
                try:
                    await bot.delete_message(chat_id, old_data['message_id'])
                except:
                    pass
            if 'timeout' in old_data:
                old_data['timeout'].cancel()
            del verification_data[user_id]
        
        # Создаем заново верификацию
        num1 = random.randint(1, 9)
        num2 = random.randint(1, 9)
        answer = num1 * num2
        
        options = [answer]
        while len(options) < 3:
            wrong = answer + random.randint(-5, 5)
            if wrong != answer and wrong > 0 and wrong not in options:
                options.append(wrong)
        random.shuffle(options)
        
        keyboard = Keyboards.verification([(str(opt), opt) for opt in options])
        user_mention = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
        
        msg = await bot.send_message(
            chat_id,
            VERIFICATION_REMINDER.format(user_mention=user_mention) + "\n\n" +
            VERIFICATION_START.format(
                user_mention=user_mention,
                num1=num1,
                num2=num2,
                timeout=VERIFY_TIMEOUT,
                attempts=MAX_ATTEMPTS
            ),
            reply_markup=keyboard
        )
        
        asyncio.create_task(delete_message_after_delay(chat_id, msg.message_id, DELETE_DELAY))
        
        timeout_task = asyncio.create_task(verification_timeout(chat_id, user_id))
        verification_data[user_id] = {
            'chat_id': chat_id,
            'answer': answer,
            'attempts': 0,
            'timeout': timeout_task,
            'user': message.from_user,
            'message_id': msg.message_id
        }
        return
    
    # Проверка на спам
    forbidden_words = db.get_forbidden_words()
    if forbidden_words:
        text = message.text or message.caption or ""
        found, word = TextNormalizer.check_forbidden(text, forbidden_words)
        if found:
            try:
                await message.delete()
            except:
                pass
            
            try:
                await bot.restrict_chat_member(chat_id, user_id, permissions=ChatPermissions(can_send_messages=False))
            except:
                pass
            
            db.ban_user(user_id, chat_id, "Спам")
            db.update_stats(chat_id, 'messages_deleted')
            db.update_stats(chat_id, 'users_restricted')
            db.add_log('spam', chat_id, user_id, message.from_user.username or "", f"Найдено слово: {text}")
            
            await bot.send_message(OWNER_ID, f"🚫 Забанен спамер!\n👤 {message.from_user.full_name}\n🆔 ID: {user_id}\n📝 Текст: {text}")
            await send_and_delete(chat_id, f"🚫 {message.from_user.first_name}, вы забанены за спам!")
            return
    
    db.update_stats(chat_id, 'messages')

# ============================================================
# КОМАНДЫ
# ============================================================

@dp.message(Command("start"))
async def start_command(message: Message):
    await send_and_delete(message.chat.id, "🤖 Привет! Я бот для защиты групп от спама.")

@dp.message(Command("admin"))
async def admin_command(message: Message):
    if message.from_user.id != OWNER_ID:
        await send_and_delete(message.chat.id, "⛔ Доступ запрещен!")
        return
    await message.answer("👋 Привет, владелец!", reply_markup=Keyboards.admin_main())

@dp.message(lambda m: m.text == "📊 Статистика" and m.from_user.id == OWNER_ID)
async def admin_stats(message: Message):
    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT group_id, title FROM groups')
        groups = cursor.fetchall()
    
    if not groups:
        await message.answer("📊 Нет данных")
        return
    
    for group in groups:
        stats = db.get_stats(group['group_id'], 30)
        if stats:
            total_messages = sum(s['messages'] for s in stats)
            total_new = sum(s['new_members'] for s in stats)
            total_verified = sum(s['verifications_passed'] for s in stats)
            await message.answer(
                f"📊 **{group['title'] or group['group_id']}**\n"
                f"📨 Сообщений: {total_messages}\n"
                f"👤 Новых: {total_new}\n"
                f"✅ Прошли: {total_verified}"
            )

@dp.message(lambda m: m.text == "📝 Слова" and m.from_user.id == OWNER_ID)
async def admin_words(message: Message):
    words = db.get_forbidden_words()
    await message.answer(f"📝 **Слов в фильтре:** {len(words)}")

@dp.message(lambda m: m.text == "➕ Добавить слово" and m.from_user.id == OWNER_ID)
async def admin_add_word(message: Message, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_word)
    await message.answer("📝 Отправьте слово для добавления:", reply_markup=Keyboards.cancel())

@dp.message(AdminStates.waiting_for_word)
async def process_add_word(message: Message, state: FSMContext):
    word = message.text.lower().strip()
    if len(word) < 2:
        await message.answer("❌ Слишком короткое слово")
        return
    db.add_forbidden_word(word)
    db.add_log('word_add', 0, message.from_user.id, message.from_user.username, word)
    await message.answer(f"✅ Слово '{word}' добавлено!")
    await state.clear()

@dp.message(lambda m: m.text == "➖ Удалить слово" and m.from_user.id == OWNER_ID)
async def admin_remove_word(message: Message, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_word_remove)
    await message.answer("📝 Отправьте слово для удаления:", reply_markup=Keyboards.cancel())

@dp.message(AdminStates.waiting_for_word_remove)
async def process_remove_word(message: Message, state: FSMContext):
    word = message.text.lower().strip()
    db.remove_forbidden_word(word)
    db.add_log('word_remove', 0, message.from_user.id, message.from_user.username, word)
    await message.answer(f"✅ Слово '{word}' удалено!")
    await state.clear()

@dp.message(lambda m: m.text == "📋 Список слов" and m.from_user.id == OWNER_ID)
async def admin_list_words(message: Message):
    words = db.get_forbidden_words()
    if not words:
        await message.answer("📋 Список слов пуст")
        return
    chunks = [list(words[i:i+50]) for i in range(0, len(words), 50)]
    for i, chunk in enumerate(chunks, 1):
        await message.answer(f"📋 Слова (часть {i}/{len(chunks)}):\n" + "\n".join(f"• {w}" for w in chunk))

@dp.message(lambda m: m.text == "📤 Экспорт слов" and m.from_user.id == OWNER_ID)
async def admin_export_words(message: Message):
    words = db.get_forbidden_words()
    if not words:
        await message.answer("📋 Список слов пуст")
        return
    content = "\n".join(sorted(words))
    file_path = "exported_words.txt"
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    await message.answer_document(FSInputFile(file_path), caption="📤 Экспорт слов")
    os.remove(file_path)

@dp.message(lambda m: m.text == "📥 Импорт слов" and m.from_user.id == OWNER_ID)
async def admin_import_words(message: Message, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_import)
    await message.answer("📥 Отправьте .txt файл со словами:", reply_markup=Keyboards.cancel())

@dp.message(AdminStates.waiting_for_import, F.document)
async def process_import_words(message: Message, state: FSMContext):
    document = message.document
    if not document.file_name.endswith('.txt'):
        await message.answer("❌ Отправьте .txt файл")
        return
    try:
        file = await bot.get_file(document.file_id)
        file_bytes = await bot.download_file(file.file_path)
        content = file_bytes.decode('utf-8', errors='ignore')
        words = [w.strip().lower() for w in content.splitlines() if w.strip()]
        added = 0
        for word in words:
            if len(word) >= 2:
                db.add_forbidden_word(word)
                added += 1
        await message.answer(f"✅ Импортировано {added} слов")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    await state.clear()

@dp.message(lambda m: m.text == "🛡️ Белый список" and m.from_user.id == OWNER_ID)
async def admin_whitelist(message: Message):
    whitelist = db.get_whitelist_users()
    await message.answer(
        f"🛡️ **Белый список:** {len(whitelist)} пользователей\n\n"
        "Команды:\n/whitelist_add <id>\n/whitelist_remove <id>\n/whitelist_list"
    )

@dp.message(Command("whitelist_add"))
async def whitelist_add(message: Message, command: CommandObject):
    if message.from_user.id != OWNER_ID:
        return
    if not command.args:
        await message.answer("❌ /whitelist_add <id>")
        return
    try:
        user_id = int(command.args)
        db.add_whitelist_user(user_id)
        await message.answer(f"✅ Пользователь {user_id} добавлен")
    except ValueError:
        await message.answer("❌ Неверный ID")

@dp.message(Command("whitelist_remove"))
async def whitelist_remove(message: Message, command: CommandObject):
    if message.from_user.id != OWNER_ID:
        return
    if not command.args:
        await message.answer("❌ /whitelist_remove <id>")
        return
    try:
        user_id = int(command.args)
        db.remove_whitelist_user(user_id)
        await message.answer(f"✅ Пользователь {user_id} удален")
    except ValueError:
        await message.answer("❌ Неверный ID")

@dp.message(Command("whitelist_list"))
async def whitelist_list(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    whitelist = db.get_whitelist_users()
    if whitelist:
        await message.answer("🛡️ **Белый список:**\n" + "\n".join(f"• {uid}" for uid in whitelist))
    else:
        await message.answer("🛡️ Белый список пуст")

@dp.message(lambda m: m.text == "📜 Логи" and m.from_user.id == OWNER_ID)
async def admin_logs(message: Message):
    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM logs ORDER BY timestamp DESC LIMIT 20')
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
    settings = {
        'verification_enabled': db.get_setting('verification_enabled', '1'),
        'verification_attempts': db.get_setting('verification_attempts', '3'),
        'verification_timeout': db.get_setting('verification_timeout', '120'),
        'delete_delay': db.get_setting('delete_delay', '60'),
    }
    await message.answer(
        f"⚙️ **Настройки**\n"
        f"🔐 Верификация: {'✅ Вкл' if settings['verification_enabled'] == '1' else '❌ Выкл'}\n"
        f"🔄 Попыток: {settings['verification_attempts']}\n"
        f"⏱ Таймаут: {settings['verification_timeout']} сек\n"
        f"🗑 Удаление: {settings['delete_delay']} сек"
    )

@dp.message(lambda m: m.text == "📊 Отправить отчет" and m.from_user.id == OWNER_ID)
async def admin_send_report(message: Message):
    await send_daily_report()
    await message.answer("✅ Отчет отправлен!")

# ============================================================
# ОТЧЕТЫ
# ============================================================

async def send_daily_report():
    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT group_id, title FROM groups')
        groups = cursor.fetchall()
    
    report = f"📊 **ЕЖЕДНЕВНЫЙ ОТЧЕТ**\n📅 {datetime.now().strftime('%d.%m.%Y')}\n\n"
    
    for group in groups:
        today = datetime.now().strftime("%Y-%m-%d")
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM statistics WHERE group_id = ? AND date = ?', (group['group_id'], today))
            stats = cursor.fetchone()
        if stats:
            report += f"**{group['title'] or group['group_id']}**\n"
            report += f"├ 📨 Сообщений: {stats['messages']}\n"
            report += f"├ 👤 Новых: {stats['new_members']}\n"
            report += f"├ ✅ Прошли: {stats['verifications_passed']}\n"
            report += f"├ ❌ Не прошли: {stats['verifications_failed']}\n"
            report += f"├ 🗑 Удалено: {stats['messages_deleted']}\n"
            report += f"└ 🚫 Ограничено: {stats['users_restricted']}\n\n"
    
    try:
        await bot.send_message(OWNER_ID, report)
    except Exception as e:
        logger.error(f"Ошибка отчета: {e}")

@dp.callback_query(lambda c: c.data == "cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer("✅ Отменено")

# ============================================================
# ЗАПУСК
# ============================================================

async def init_groups():
    try:
        updates = await bot.get_updates(limit=100)
        for update in updates:
            if update.message and update.message.chat.type in ['group', 'supergroup']:
                chat = update.message.chat
                with db.connect() as conn:
                    cursor = conn.cursor()
                    cursor.execute('INSERT OR IGNORE INTO groups (group_id, title) VALUES (?, ?)', (chat.id, chat.title))
                    conn.commit()
                    try:
                        members = await bot.get_chat_administrators(chat.id)
                        for member in members:
                            if not member.user.is_bot:
                                db.mark_verified(member.user.id, chat.id, member.user.username, member.user.first_name)
                    except:
                        pass
        logger.info("✅ Группы инициализированы")
    except Exception as e:
        logger.error(f"Ошибка инициализации: {e}")

async def scheduler():
    while True:
        aioschedule.run_pending()
        await asyncio.sleep(60)

async def main():
    await bot.set_my_commands([
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="admin", description="Админ-панель"),
    ])
    
    await init_groups()
    
    try:
        report_hour, report_minute = map(int, REPORT_TIME.split(':'))
        aioschedule.every().day.at(f"{report_hour:02d}:{report_minute:02d}").do(
            lambda: asyncio.create_task(send_daily_report())
        )
    except:
        aioschedule.every().day.at("23:59").do(lambda: asyncio.create_task(send_daily_report()))
    
    asyncio.create_task(scheduler())
    
    logger.info("🚀 БОТ ЗАПУЩЕН!")
    logger.info(f"🤖 @{await bot.get_me()}")
    logger.info("=" * 50)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
