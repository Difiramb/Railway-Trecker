from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo
import yaml
from db import Database
from models import Observation
from predictor import Predictor

app = Flask(__name__)

# Загружаем конфиг и инициализируем БД при старте
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

db = Database(config["database"])
predictor = Predictor(config, db, config["schedule_path"])
tz = ZoneInfo(config["timezone"])

@app.route('/api/status', methods=['GET'])
def get_status():
    try:
        now = datetime.now(tz)
        pred = predictor.predict(now=now)
        # Используем ту же логику форматирования, но можно сделать короче
        text = predictor.format_reply(pred, now=now)
        return jsonify({"text": text, "status": pred.status})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/observe', methods=['POST'])
def observe():
    try:
        data = request.json
        vk_user_id = data.get('vk_user_id')
        
        if not vk_user_id:
            return jsonify({"error": "No user ID"}), 400

        # Хешируем ID так же, как в боте (для защиты приватности)
        from bot import make_user_hash
        user_hash = make_user_hash(vk_user_id)

        now = datetime.now(tz)
        now_utc = now.astimezone(timezone.utc)

        db.add_observation(
            Observation(
                ts=now_utc,
                source="user",
                status=data.get('status'),
                wait_min=data.get('wait_min'),
                user_hash=user_hash,
                plausibility=1.0, # Пока без фильтра, чтобы не усложнять
                train_type=data.get('train_type')
            )
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def run_api():
    # BotHost обычно передает порт через переменную окружения PORT
    import os
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
