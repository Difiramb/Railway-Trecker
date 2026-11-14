import os
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from maxapi import Bot, Dispatcher, Command
from maxapi.types import MessageCreated

from db import Database
from models import Observation
from predictor import Predictor
from plausibility import PlausibilityFilter
from bot import make_user_hash  # Переиспользуем функцию хеширования

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загружаем конфиг (пути к БД и расписанию)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
import yaml
with open(os.path.join(BASE_DIR, "config.yaml"), "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# Делаем пути абсолютными
config["database"] = os.path.join(BASE_DIR, config["database"])
config["schedule_path"] = os.path.join(BASE_DIR, config["schedule_path"])
config["plausibility_path"] = os.path.join(BASE_DIR, config.get("plausibility_path", "data/plausibility.yaml"))

# Инициализация общих компонентов
db = Database(config["database"])
predictor = Predictor(config, db, config["schedule_path"])
plausibility = PlausibilityFilter(config["plausibility_path"])
tz = ZoneInfo(config["timezone"])

# Инициализация бота MAX
bot = Bot(token=os.getenv("MAX_BOT_TOKEN"))
dp = Dispatcher()

# Текст справки (можно скопировать из bot.py)
HELP_TEXT = (
    "🚂 Привет! Я бот «ЖД трекер».\n"
    "Помогаю понять, открыт переезд или закрыт.\n\n"
    "📊 СТАТУС\n"
    "Напиши «статус» — покажу текущую обстановку.\n\n"
    "🚗 ЗАКРЫТ\n"
    "Напиши «закрыт» или «закрыт 15» (если уже стоишь 15 минут).\n"
    "Можно уточнить тип поезда: «закрыт 15 пассажирский».\n\n"
    "✅ ОТКРЫТ\n"
    "Напиши «открыт» — если только что проехал.\n\n"
    "❓ ПОМОЩЬ\n"
    "Это сообщение."
)

@dp.message_created(Command("start"))
async def cmd_start(event: MessageCreated):
    await event.message.answer(HELP_TEXT)

@dp.message_created(Command("помощь"))
async def cmd_help(event: MessageCreated):
    await event.message.answer(HELP_TEXT)

@dp.message_created(Command("статус"))
async def cmd_status(event: MessageCreated):
    now = datetime.now(tz)
    pred = predictor.predict(now=now)
    db.add_prediction(pred, now)
    reply = predictor.format_reply(pred, now=now)
    await event.message.answer(reply)

@dp.message_created(Command("закрыт"))
async def cmd_closed(event: MessageCreated):
    # Парсим текст сообщения: "закрыт", "закрыт 15", "закрыт 15 пассажирский"
    text = event.message.body.text.strip().lower()
    parts = text.split()
    
    wait_min = None
    train_type = None
    
    if len(parts) >= 2 and parts[1].isdigit():
        wait_min = int(parts[1])
        if len(parts) >= 3:
            # Простое сопоставление типов
            type_map = {"пассажирский": "passenger", "товарный": "freight", "технический": "technical"}
            train_type = type_map.get(parts[2])
    
    # Хешируем ID пользователя MAX
    user_hash = make_user_hash(str(event.from_.id))
    
    now = datetime.now(tz)
    now_utc = now.astimezone(timezone.utc)
    
    # Оценка правдоподобности
    plaus_score, reasons = plausibility.score(user_hash, "closed", wait_min, now, db)
    if reasons:
        logger.info(f"[MAX plausibility] user={user_hash[:8]} score={plaus_score:.2f} reasons={reasons}")
    
    db.add_observation(
        Observation(
            ts=now_utc,
            source="user",
            status="closed",
            wait_min=wait_min,
            user_hash=user_hash,
            plausibility=plaus_score,
            train_type=train_type
        )
    )
    
    if wait_min is None:
        reply = "Спасибо! Записал: переезд закрыт. 🙌\nЕсли знаешь, сколько уже стоишь — напиши «закрыт 15»."
    else:
        reply = f"Спасибо! Записал: переезд закрыт, ожидание {wait_min} мин."
    
    await event.message.answer(reply)

@dp.message_created(Command("открыт"))
async def cmd_open(event: MessageCreated):
    user_hash = make_user_hash(str(event.from_.id))
    now = datetime.now(tz)
    now_utc = now.astimezone(timezone.utc)
    
    plaus_score, reasons = plausibility.score(user_hash, "open", 0, now, db)
    
    db.add_observation(
        Observation(
            ts=now_utc,
            source="user",
            status="open",
            wait_min=0,
            user_hash=user_hash,
            plausibility=plaus_score
        )
    )
    await event.message.answer("Спасибо! Записал: переезд открыт. ✅")

async def run_max_bot():
    """Запускает MAX-бота через Long Polling."""
    logger.info("[MAX] Бот запускается...")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"[MAX] Ошибка при запуске: {e}")

def start_max_bot_in_thread():
    """Синхронная обёртка для запуска в отдельном потоке."""
    asyncio.run(run_max_bot())
