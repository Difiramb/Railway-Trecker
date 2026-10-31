import os

import requests


class YandexTrafficProvider:
    """
    Заглушка-адаптер. Включайте только если есть легальный источник
    данных о пробках/заторах и понятный формат ответа.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get("enabled", False))
        self.endpoint = self.cfg.get("endpoint", "")
        key_env = self.cfg.get("api_key_env", "YANDEX_API_KEY")
        self.api_key = os.getenv(key_env, "")

    def fetch(self, lat: float, lon: float) -> dict | None:
        if not self.enabled or not self.endpoint or not self.api_key:
            return None

        response = requests.get(
            self.endpoint,
            params={"lat": lat, "lon": lon, "apikey": self.api_key},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        # Адаптируйте под фактический ответ вашего легального API.
        return {
            "jam_length_m": data.get("jam_length_m"),
            "level": data.get("level"),
            "raw": data,
        }
