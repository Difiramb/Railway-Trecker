import hashlib
import os
import random
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import vk_api
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.longpoll import VkEventType, VkLongPoll

from db import Database
from models import Observation
from plausibility import PlausibilityFilter
from predictor import Predictor


HELP_TEXT = (
    "Команды:\n"
    "• «статус» — прогноз по переезду\n"
    "• «закрыт 15» — переезд закрыт, стоите ~15 мин\n"
    "• «закрыт» — переезд закрыт, время неизвестно\n"
    "• «открыт» — переезд открыт\n"
    "• «помощь» — это сообщение"
)


def make_user_hash(user_id: int) -> str:
    salt = os.getenv("USER_HASH_SALT", "change-me")
    raw = f"{salt}:{user_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def build_main_keyboard() -> VkKeyboard:
    """Постоянная клавиатура с основными действиями."""
    kb = VkKeyboard(one_time=False)

    kb.add_button("Статус", color=VkKeyboardColor.PRIMARY)
    kb.add_button("Помощь", color=VkKeyboardColor.SECONDARY)
    kb.add_line()
    kb.add_button("Закрыт", color=VkKeyboardColor.NEGATIVE)
    kb.add_button("Открыт", color=VkKeyboardColor.POSITIVE)

    return kb


class CrossingVKBot:
    def __init__(self, config: dict, db: Database, predictor: Predictor):
        token = os.getenv(config["vk"]["token_env"])
        if not token:
            raise RuntimeError(f"Не задан токен VK в переменной {config['vk']['token_env']}")

        group_id = config["vk"].get("group_id")
        if not group_id:
            raise RuntimeError("Укажите vk.group_id в config.yaml")

        self.config = config
        self.db = db
        self.predictor = predictor
        self.tz = ZoneInfo(config["timezone"])
        self.plausibility = PlausibilityFilter(
            config.get("plausibility_path", "data/plausibility.yaml")
        )
        self.keyboard = build_main_keyboard()

        self.vk_session = vk_api.VkApi(token=token)
        self.vk = self.vk_session.get_api()
        self.longpoll = VkLongPoll(self.vk_session, group_id=int(group_id))

    def run(self) -> None:
        print(f"Бот запущен, слушаю сообщество id={self.config['vk']['group_id']}", flush=True)
        for event in self.longpoll.listen():
            if event.type == VkEventType.MESSAGE_NEW and event.to_me:
                try:
                    self.handle(event.user_id, event.text)
                except Exception as exc:
                    print(f"[error] user={event.user_id} text={event.text!r}: {exc}", flush=True)
                    try:
                        self.send(event.user_id, f"Ошибка обработки: {exc}")
                    except Exception:
                        pass

    def send(self, user_id: int, text: str) -> None:
        self.vk.messages.send(
            user_id=user_id,
            message=text,
            random_id=random.randint(1, 2**31 - 1),
            keyboard=self.keyboard.get_keyboard(),
        )

    def _record(self, user_id: int, status: str, wait_min: int | None, now, now_utc) -> float:
        user_hash = make_user_hash(user_id)
        plausibility, reasons = self.plausibility.score(
            user_hash, status, wait_min, now, self.db
        )
        if reasons:
            print(
                f"[plausibility] user={user_hash[:8]} status={status} "
                f"wait={wait_min} score={plausibility:.2f} reasons={reasons}",
                flush=True,
            )
        self.db.add_observation(
            Observation(
                ts=now_utc,
                source="user",
                status=status,
                wait_min=wait_min,
                user_hash=user_hash,
                plausibility=plausibility,
            )
        )
        return plausibility

    def handle(self, user_id: int, text: str | None) -> None:
        text = (text or "").strip().lower()
        now = datetime.now(self.tz)
        now_utc = now.astimezone(timezone.utc)

        if text in {"помощь", "help", "/help", "начать", "/start", "команды"} or not text:
            self.send(user_id, HELP_TEXT)
            return

        if text in {"статус", "/статус", "что там", "переезд"}:
            pred = self.predictor.predict(now=now)
            self.db.add_prediction(pred, now)
            self.send(user_id, self.predictor.format_reply(pred, now=now))
            return

        if re.fullmatch(r"/?открыт", text):
            self._record(user_id, "open", 0, now, now_utc)
            self.send(user_id, "Спасибо! Записал: переезд открыт.")
            return

        m = re.match(r"^/?закрыт(?:\s+(\d+))?\s*$", text)
        if m:
            wait_min = int(m.group(1)) if m.group(1) else None
            self._record(user_id, "closed", wait_min, now, now_utc)
            suffix = f", ожидание {wait_min} мин." if wait_min is not None else "."
            self.send(user_id, "Спасибо! Записал: переезд закрыт" + suffix)
            return

        self.send(user_id, HELP_TEXT)
