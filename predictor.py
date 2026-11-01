import math
from datetime import datetime, time, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

import yaml

from db import Database
from models import Prediction
from yandex_provider import YandexTrafficProvider


class Predictor:
    def __init__(self, config: dict, db: Database, schedule_path: str):
        self.cfg = config
        self.db = db
        self.tz = ZoneInfo(config["timezone"])
        self.weights = config["prediction"]["weights"]
        self.closed_threshold = float(config["prediction"]["closed_threshold"])
        self.open_threshold = float(config["prediction"]["open_threshold"])
        self.ttl_min = int(config["prediction"]["report_ttl_min"])
        self.yandex = YandexTrafficProvider(config.get("yandex", {}))

        try:
            with open(schedule_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self.schedule = data["schedule"]
            self.peaks = data.get("peaks", [])
            print(f"[predictor] schedule loaded from {schedule_path}", flush=True)
        except FileNotFoundError:
            print(
                f"[predictor] WARNING: {schedule_path} not found, using built-in defaults",
                flush=True,
            )
            self.schedule = [
                {"id": "night", "start": "03:00", "end": "04:00",
                 "duration_min": [10, 20], "probability": 0.85},
                {"id": "morning", "start": "07:30", "end": "08:10",
                 "duration_min": [10, 20], "probability": 0.85},
                {"id": "noon", "start": "12:00", "end": "13:00",
                 "duration_min": [15, 30], "probability": 0.75},
                {"id": "every2h_14", "start": "14:00", "end": "15:00",
                 "duration_min": [10, 40], "probability": 0.65},
                {"id": "every2h_16", "start": "16:00", "end": "17:00",
                 "duration_min": [10, 40], "probability": 0.65},
                {"id": "every2h_18", "start": "18:00", "end": "19:00",
                 "duration_min": [10, 40], "probability": 0.65},
                {"id": "evening", "start": "21:00", "end": "21:40",
                 "duration_min": [10, 20], "probability": 0.75},
            ]
            self.peaks = [
                {"id": "peak_0700", "time": "07:00", "window_min": 5,
                 "duration_min": [10, 20], "probability": 0.55},
                {"id": "peak_0845", "time": "08:45", "window_min": 5,
                 "duration_min": [10, 20], "probability": 0.55},
                {"id": "peak_1000", "time": "10:00", "window_min": 5,
                 "duration_min": [10, 25], "probability": 0.55},
                {"id": "peak_1400", "time": "14:00", "window_min": 5,
                 "duration_min": [10, 40], "probability": 0.55},
                {"id": "peak_1700", "time": "17:00", "window_min": 5,
                 "duration_min": [10, 40], "probability": 0.55},
                {"id": "peak_1900", "time": "19:00", "window_min": 5,
                 "duration_min": [10, 20], "probability": 0.55},
            ]

    def predict(self, now: datetime | None = None, use_yandex: bool = True) -> Prediction:
        now = now or datetime.now(self.tz)
        now_utc = now.astimezone(timezone.utc)
        since = now_utc - timedelta(minutes=self.ttl_min)

        observations = self.db.recent_observations(since)
        schedule_item = self._schedule_for(now)
        peak_item = self._peak_for(now)

        # items: (p_closed, weight, estimated_wait_min, source)
        items: list[tuple[float, float, int | None, str]] = []

        # 1. Расписание-приор
        p_schedule = float(schedule_item.get("probability", 0.65)) if schedule_item else 0.05
        items.append((p_schedule, self.weights["schedule"], None, "schedule"))

        # 1a. Пик — дополнительный сигнал поверх расписания, не замена
        if peak_item:
            p_peak = float(peak_item.get("probability", 0.55))
            items.append((p_peak, self.weights.get("peak", 0.35), None, "peak"))

        # 2. Сообщения пользователей
        for obs in observations:
            if obs.source != "user":
                continue

            age_min = max(0.0, (now_utc - obs.ts.astimezone(timezone.utc)).total_seconds() / 60.0)
            decay = math.exp(-age_min / max(1, self.ttl_min))

            plaus = getattr(obs, "plausibility", 1.0) or 1.0

            if obs.status == "closed":
                weight = self.weights["user_closed"] * decay * plaus
                wait_est = None
                if obs.wait_min is not None:
                    reference = schedule_item or peak_item
                    med_duration = self._median_duration(now, reference)
                    wait_est = max(0, int(round(med_duration - obs.wait_min)))
                items.append((1.0, weight, wait_est, "user_closed"))

            elif obs.status == "open":
                weight = self.weights["user_open"] * decay * plaus
                items.append((0.0, weight, 0, "user_open"))

        # 3. Яндекс-провайдер, если включён
        yandex_data = None
        if use_yandex and self.yandex.enabled:
            try:
                yandex_data = self.yandex.fetch(
                    self.cfg["crossing"]["lat"],
                    self.cfg["crossing"]["lon"],
                )
            except Exception:
                yandex_data = None

        if yandex_data:
            jam_len = float(yandex_data.get("jam_length_m") or 0)
            threshold = float(self.cfg["yandex"].get("jam_threshold_m", 150))
            p_yandex = 0.85 if jam_len >= threshold else 0.15

            wait_yandex = None
            if jam_len > 0:
                k = float(self.cfg["yandex"].get("jam_length_to_wait_min_per_100m", 0.7))
                wait_yandex = int(round(jam_len / 100.0 * k))

            items.append((p_yandex, self.weights["yandex"], wait_yandex, "yandex"))

        # Комбинируем вероятность
        total_weight = sum(w for _, w, _, _ in items)
        p_closed = (
            sum(p * w for p, w, _, _ in items) / total_weight
            if total_weight > 0
            else 0.5
        )

        if p_closed >= self.closed_threshold:
            status = "closed"
        elif p_closed <= self.open_threshold:
            status = "open"
        else:
            status = "unknown"

        waits = [w for _, _, w, _ in items if w is not None]
        expected_wait = int(round(median(waits))) if waits else None

        if status == "closed" and expected_wait is None:
            fallback = schedule_item or peak_item
            expected_wait = int(round(self._median_duration(now, fallback)))

        expected_open_at = None
        if status == "closed" and expected_wait is not None:
            expected_open_at = now + timedelta(minutes=expected_wait)

        # confidence: согласованность источников + объём данных
        p_values = [p for p, _, _, _ in items]
        spread = max(p_values) - min(p_values) if len(p_values) > 1 else 0.0
        agreement = 1.0 - spread
        volume = min(1.0, total_weight / 3.0)
        confidence = round(0.6 * agreement + 0.4 * volume, 2)

        details = {
            "schedule": schedule_item,
            "peak": peak_item,
            "observations_count": len(observations),
            "yandex": yandex_data,
            "items": [
                {"source": source, "p": round(p, 3), "weight": round(w, 3), "wait": wait}
                for p, w, wait, source in items
            ],
        }

        return Prediction(
            status=status,
            p_closed=p_closed,
            expected_wait_min=expected_wait,
            expected_open_at=expected_open_at,
            confidence=confidence,
            details=details,
        )

    def format_reply(self, pred: Prediction, now: datetime | None = None) -> str:
        now = now or datetime.now(self.tz)

        if pred.status == "closed":
            text = f"🔴 Переезд вероятно закрыт. P(закрыт) = {pred.p_closed:.0%}."
            if pred.expected_wait_min is not None:
                text += f" Ожидание ≈ {pred.expected_wait_min} мин."
            if pred.expected_open_at is not None:
                text += f" Откроется около {pred.expected_open_at.strftime('%H:%M')}."
        elif pred.status == "open":
            text = f"🟢 Переезд вероятно открыт. P(закрыт) = {pred.p_closed:.0%}."
            next_window = self._next_window(now)
            if next_window:
                start_dt, item = next_window
                text += (
                    f" Следующее вероятное окно: "
                    f"{item['start']}–{item['end']}."
                )
        else:
            text = (
                f"🟡 Недостаточно данных. P(закрыт) = {pred.p_closed:.0%}. "
                "Лучше ориентироваться на свежие сообщения."
            )

        text += f"\nУверенность: {pred.confidence:.0%}."
        text += "\nСообщите: «закрыт 15» или «открыт»."
        return text

    def _schedule_for(self, now: datetime) -> dict | None:
        current = now.time()
        for item in self.schedule:
            start = time.fromisoformat(item["start"])
            end = time.fromisoformat(item["end"])
            if start <= current <= end:
                return item
        return None

    def _peak_for(self, now: datetime) -> dict | None:
        """Возвращает активный пик, если now попадает в его окно ±window_min."""
        for peak in self.peaks:
            center = time.fromisoformat(peak["time"])
            window = int(peak.get("window_min", 5))
            center_dt = datetime.combine(now.date(), center, tzinfo=self.tz)
            delta_min = abs((now - center_dt).total_seconds()) / 60.0
            if delta_min <= window:
                return peak
        return None

    def _next_window(self, now: datetime) -> tuple[datetime, dict] | None:
        candidates = []
        for item in self.schedule:
            start = time.fromisoformat(item["start"])
            start_dt = datetime.combine(now.date(), start, tzinfo=self.tz)
            if start_dt <= now:
                start_dt += timedelta(days=1)
            candidates.append((start_dt, item))
        return min(candidates, key=lambda x: x[0]) if candidates else None

    @staticmethod
    def _median_duration(now: datetime, schedule_item: dict | None) -> float:
        if schedule_item and schedule_item.get("duration_min"):
            a, b = schedule_item["duration_min"]
            return (float(a) + float(b)) / 2.0
        return 20.0
