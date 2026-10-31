import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

load_dotenv()

from db import Database
from models import Observation
from predictor import Predictor


COMMANDS = """
Команды:
  статус          — прогноз по переезду
  закрыт 15       — переезд закрыт, стоите ~15 мин
  открыт          — переезд открыт
  история         — последние 10 наблюдений
  выход           — выйти
"""


def main() -> None:
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    db = Database(config["database"])
    predictor = Predictor(config, db, config["schedule_path"])
    tz = ZoneInfo(config["timezone"])

    print(f"Локальный CLI. Переезд: {config['crossing']['name']}")
    print(COMMANDS)

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        lowered = line.lower()
        now = datetime.now(tz)

        if lowered in {"выход", "exit", "quit", "q"}:
            break

        if lowered in {"статус", "status", "s"}:
            pred = predictor.predict(now=now)
            db.add_prediction(pred, now)
            print(predictor.format_reply(pred, now=now))
            print(f"   [P(закрыт)={pred.p_closed:.2f}, confidence={pred.confidence:.2f}]")
            continue

        if lowered in {"история", "history", "h"}:
            rows = db.conn.execute(
                """
                SELECT ts_utc, source, status, wait_min
                FROM observations
                ORDER BY ts_utc DESC
                LIMIT 10
                """
            ).fetchall()
            if not rows:
                print("(пусто)")
                continue
            for r in rows:
                print(
                    f"{r['ts_utc']}  {r['source']:6}  {r['status']:7}  "
                    f"wait={r['wait_min']}"
                )
            continue

        if lowered.startswith("закрыт"):
            parts = line.split(maxsplit=1)
            wait_min = None
            if len(parts) == 2 and parts[1].strip().isdigit():
                wait_min = int(parts[1].strip())

            db.add_observation(
                Observation(
                    ts=now,
                    source="user",
                    status="closed",
                    wait_min=wait_min,
                )
            )
            print(f"Записал: закрыт, wait={wait_min}")
            continue

        if lowered in {"открыт", "open"}:
            db.add_observation(
                Observation(
                    ts=now,
                    source="user",
                    status="open",
                    wait_min=0,
                )
            )
            print("Записал: открыт")
            continue

        print(COMMANDS)

    print("Пока.")


if __name__ == "__main__":
    sys.exit(main())
