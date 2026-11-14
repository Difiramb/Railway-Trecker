import os
import sys
import threading  # <-- Необходимо для фоновых задач

import requests
import yaml
from dotenv import load_dotenv

# Настраиваем базовую директорию и переменные окружения
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Импорт наших модулей
from bot import CrossingVKBot
from db import Database
from predictor import Predictor
from api import run_api  # <-- Импорт API-сервера (Flask)
from max_bot import start_max_bot_in_thread  # <-- Импорт MAX-бота


def sync_from_github(config: dict, url_key: str, path_key: str) -> None:
    """Скачивает файл по url_key и кладёт по пути path_key."""
    url = config.get(url_key)
    if not url:
        print(f"[run] {url_key} not set, skip sync", flush=True)
        return
    path = config[path_key]
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(r.text)
        print(f"[run] synced: {path} ({len(r.text)} bytes)", flush=True)
    except Exception as e:
        print(f"[run] WARNING: sync failed for {path}: {e}", flush=True)


def main() -> None:
    config_path = os.path.join(BASE_DIR, "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Делаем пути абсолютными
    config["database"] = os.path.join(BASE_DIR, config["database"])
    config["schedule_path"] = os.path.join(BASE_DIR, config["schedule_path"])
    config["plausibility_path"] = os.path.join(
        BASE_DIR, config.get("plausibility_path", "data/plausibility.yaml")
    )

    print("=== START ===", flush=True)
    print("schedule_path:", config["schedule_path"], flush=True)
    print("plausibility_path:", config["plausibility_path"], flush=True)
    print("db:", config["database"], flush=True)

    # Синхронизация YAML-файлов с GitHub
    sync_from_github(config, "schedule_source_url", "schedule_path")
    sync_from_github(config, "plausibility_source_url", "plausibility_path")

    print("exists schedule:", os.path.exists(config["schedule_path"]), flush=True)
    print("exists plausibility:", os.path.exists(config["plausibility_path"]), flush=True)

    # Инициализация базы данных и прогнозатора
    db = Database(config["database"])
    predictor = Predictor(config, db, config["schedule_path"])
    
    # Инициализация VK-бота
    bot = CrossingVKBot(config, db, predictor)

    # --- ЗАПУСК В ФОНОВЫХ ПОТОКАХ ---
    
    # 1. Запуск веб-сервера (Flask API)
    print("[run] starting API server in background thread...", flush=True)
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()

    # 2. Запуск MAX-бота
    print("[run] starting MAX bot in background thread...", flush=True)
    max_thread = threading.Thread(target=start_max_bot_in_thread, daemon=True)
    max_thread.start()

    # --- ЗАПУСК VK-БОТА В ОСНОВНОМ ПОТОКЕ ---
    # VK-бот блокирует основной поток (это нормально, он слушает события)
    print("[run] starting VK bot in main thread...", flush=True)
    bot.run()


if __name__ == "__main__":
    main()
