import os
import sys

import requests
import yaml
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
load_dotenv(os.path.join(BASE_DIR, ".env"))

from bot import CrossingVKBot
from db import Database
from predictor import Predictor


def sync_from_github(config: dict, url_key: str, path_key: str) -> None:
    url = config.get(url_key)
    if not url:
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

    config["database"] = os.path.join(BASE_DIR, config["database"])
    config["schedule_path"] = os.path.join(BASE_DIR, config["schedule_path"])
    config["plausibility_path"] = os.path.join(
        BASE_DIR, config.get("plausibility_path", "data/plausibility.yaml")
    )

    print("=== START ===", flush=True)
    print("schedule_path:", config["schedule_path"], flush=True)
    print("plausibility_path:", config["plausibility_path"], flush=True)
    print("db:", config["database"], flush=True)

    sync_from_github(config, "schedule_source_url", "schedule_path")
    sync_from_github(config, "plausibility_source_url", "plausibility_path")

    db = Database(config["database"])
    predictor = Predictor(config, db, config["schedule_path"])
    bot = CrossingVKBot(config, db, predictor)
    bot.run()


if __name__ == "__main__":
    main()
