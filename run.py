import yaml
from dotenv import load_dotenv

load_dotenv()  # <-- читает .env

from bot import CrossingVKBot
from db import Database
from predictor import Predictor


def main() -> None:
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    db = Database(config["database"])
    predictor = Predictor(config, db, config["schedule_path"])
    bot = CrossingVKBot(config, db, predictor)
    bot.run()


if __name__ == "__main__":
    main()
