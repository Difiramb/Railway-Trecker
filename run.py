import os
import sys

import yaml
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)                     # работаем из папки проекта
load_dotenv(os.path.join(BASE_DIR, ".env"))

from bot import CrossingVKBot
from db import Database
from predictor import Predictor


def main() -> None:
    config_path = os.path.join(BASE_DIR, "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # делаем пути из config.yaml абсолютными
    config["database"] = os.path.join(BASE_DIR, config["database"])
    config["schedule_path"] = os.path.join(BASE_DIR, config["schedule_path"])

    print("=== START ===", flush=True)
    print("schedule_path:", config["schedule_path"], flush=True)
    print("db:", config["database"], flush=True)
    print("exists schedule:", os.path.exists(config["schedule_path"]), flush=True)

    db = Database(config["database"])
    predictor = Predictor(config, db, config["schedule_path"])
    bot = CrossingVKBot(config, db, predictor)
    bot.run()


if __name__ == "__main__":
    main()
