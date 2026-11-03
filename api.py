from flask import Flask, request, jsonify
from flask_cors import CORS  # <-- Добавлено
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import yaml
import os

from db import Database
from models import Observation
from predictor import Predictor
from bot import make_user_hash

app = Flask(__name__)
CORS(app)  # <-- Разрешаем запросы отовсюду (для Mini Apps это нужно)

# Загружаем конфиг
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE_DIR, "config.yaml"), "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# Делаем пути абсолютными (как в run.py)
config["database"] = os.path.join(BASE_DIR, config["database"])
config["schedule_path"] = os.path.join(BASE_DIR, config["schedule_path"])

db = Database(config["database"])
predictor = Predictor(config, db, config["schedule_path"])
tz = ZoneInfo(config["timezone"])

@app.route('/api/status', methods=['GET'])
def get_status():
    try:
        now = datetime.now(tz)
        pred = predictor.predict(now=now)
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
                plausibility=1.0, 
                train_type=data.get('train_type')
            )
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def run_api():
    port = int(os.getenv("PORT", 5000))
    # host="0.0.0.0" обязателен для BotHost, иначе сервер не будет виден снаружи
    app.run(host="0.0.0.0", port=port)
