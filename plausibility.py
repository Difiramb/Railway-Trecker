from datetime import datetime, timedelta
from pathlib import Path

import yaml


DEFAULTS = {
    "enabled": False,
    "notify_user": False,
    "rules": {
        "flood": {"enabled": True, "window_min": 10, "threshold_count": 5, "weight": 0.6},
        "flip_flop": {"enabled": True, "window_min": 3, "min_flips": 2, "weight": 0.6},
        "wait_regression": {"enabled": True, "window_min": 60, "weight": 0.4},
        "wait_jump": {"enabled": True, "window_min": 30, "tolerance_min": 3, "weight": 0.5},
    },
    "global_rate": {"enabled": True, "window_min": 60, "soft_limit": 15, "min_weight": 0.2},
}


class PlausibilityFilter:
    """
    Оценивает правдоподобность нового наблюдения, опираясь только на
    недавнюю историю того же пользователя. Не блокирует — возвращает
    множитель веса 0..1 для predict().
    """

    def __init__(self, config_path: str):
        self.path = Path(config_path)
        if self.path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                self.cfg = yaml.safe_load(f) or {}
        else:
            print(f"[plausibility] {config_path} not found, disabled", flush=True)
            self.cfg = {}
        self.enabled = bool(self.cfg.get("enabled", DEFAULTS["enabled"]))
        self.notify_user = bool(self.cfg.get("notify_user", DEFAULTS["notify_user"]))
        self.rules = {**DEFAULTS["rules"], **(self.cfg.get("rules") or {})}
        self.global_rate = {**DEFAULTS["global_rate"], **(self.cfg.get("global_rate") or {})}

    def score(self, user_hash, status, wait_min, now, db):
        """Возвращает (множитель 0..1, список причин)."""
        if not self.enabled or not user_hash:
            return 1.0, []

        rows = db.conn.execute(
            """
            SELECT ts_utc, status, wait_min
            FROM observations
            WHERE user_hash = ?
            ORDER BY ts_utc DESC
            LIMIT 50
            """,
            (user_hash,),
        ).fetchall()

        hist = []
        for r in rows:
            try:
                ts = datetime.fromisoformat(r["ts_utc"])
            except ValueError:
                continue
            hist.append({"ts": ts, "status": r["status"], "wait_min": r["wait_min"]})

        plausibility = 1.0
        reasons: list[str] = []

        rule = self.rules["flood"]
        if rule.get("enabled"):
            w = timedelta(minutes=int(rule.get("window_min", 10)))
            th = int(rule.get("threshold_count", 5))
            recent = [h for h in hist if (now - h["ts"]) <= w]
            if len(recent) + 1 >= th:
                plausibility *= float(rule.get("weight", 0.6))
                reasons.append(f"flood({len(recent)+1}/{rule['window_min']}min)")

        # Пинг-понг: 2+ переключения closed<->open за короткое окно.
        # Одиночный переход (open->closed или closed->open) — легитимен,
        # не штрафуем: переезд реально может закрыться через секунду после проезда.
        rule = self.rules["flip_flop"]
        if rule.get("enabled") and status in {"closed", "open"}:
            w = timedelta(minutes=float(rule.get("window_min", 3)))
            min_flips = int(rule.get("min_flips", 2))
            recent = sorted(
                [h for h in hist
                 if (now - h["ts"]) <= w and h["status"] in ("closed", "open")],
                key=lambda x: x["ts"],
            )
            seq = [h["status"] for h in recent] + [status]
            flips = sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
            if flips >= min_flips:
                plausibility *= float(rule.get("weight", 0.6))
                reasons.append(f"flip_flop({flips})")

        rule = self.rules["wait_regression"]
        if rule.get("enabled") and status == "closed" and wait_min is not None:
            w = timedelta(minutes=int(rule.get("window_min", 60)))
            prev = [h for h in hist if (now - h["ts"]) <= w
                    and h["status"] == "closed" and h["wait_min"] is not None]
            if prev:
                last_wait = prev[0]["wait_min"]
                if wait_min < last_wait - 1:
                    plausibility *= float(rule.get("weight", 0.4))
                    reasons.append(f"wait_regression({last_wait}->{wait_min})")

        rule = self.rules["wait_jump"]
        if rule.get("enabled") and status == "closed" and wait_min is not None:
            w = timedelta(minutes=int(rule.get("window_min", 30)))
            tol = float(rule.get("tolerance_min", 3))
            prev = [h for h in hist if (now - h["ts"]) <= w
                    and h["status"] == "closed" and h["wait_min"] is not None]
            if prev:
                elapsed = (now - prev[0]["ts"]).total_seconds() / 60.0
                delta = wait_min - prev[0]["wait_min"]
                if delta > elapsed + tol:
                    plausibility *= float(rule.get("weight", 0.5))
                    reasons.append(f"wait_jump(+{delta:.0f}/+{elapsed:.0f})")

        rule = self.global_rate
        if rule.get("enabled"):
            w = timedelta(minutes=int(rule.get("window_min", 60)))
            soft = int(rule.get("soft_limit", 15))
            min_w = float(rule.get("min_weight", 0.2))
            recent = [h for h in hist if (now - h["ts"]) <= w]
            n = len(recent) + 1
            if n > soft:
                t = min(1.0, (n - soft) / float(soft))
                factor = 1.0 - (1.0 - min_w) * t
                plausibility *= factor
                reasons.append(f"rate({n}/{rule['window_min']}min)")

        plausibility = max(0.0, min(1.0, plausibility))
        return plausibility, reasons
