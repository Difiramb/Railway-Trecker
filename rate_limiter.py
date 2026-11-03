import time
from collections import defaultdict, deque
from typing import Optional

import vk_api


class RateLimiter:
    """
    Двухуровневый rate limiter без внешних зависимостей.

    - incoming: не больше max_incoming сообщений от одного user_id за window_sec.
    - outgoing: token bucket для глобального ограничения исходящих запросов.
    """

    def __init__(
        self,
        incoming_max: int = 3,
        incoming_window_sec: float = 10.0,
        outgoing_rate_per_sec: float = 18.0,   # чуть ниже лимита VK (20)
        outgoing_burst: int = 25,
    ):
        # Входящие: user_id -> deque[timestamp]
        self._incoming: dict[int, deque[float]] = defaultdict(deque)
        self.incoming_max = incoming_max
        self.incoming_window = incoming_window_sec

        # Исходящие: token bucket
        self.outgoing_rate = outgoing_rate_per_sec
        self.outgoing_burst = outgoing_burst
        self._tokens = float(outgoing_burst)
        self._last_refill = time.monotonic()

    # ---------- Входящие ----------
    def allow_incoming(self, user_id: int) -> bool:
        """True — можно обрабатывать, False — пользователь слишком частит."""
        now = time.monotonic()
        q = self._incoming[user_id]

        # выбрасываем старые отметки
        cutoff = now - self.incoming_window
        while q and q[0] < cutoff:
            q.popleft()

        if len(q) >= self.incoming_max:
            return False

        q.append(now)
        # периодическая чистка, чтобы dict не разрастался
        if len(self._incoming) > 1000:
            self._cleanup(now)
        return True

    def _cleanup(self, now: float) -> None:
        cutoff = now - self.incoming_window
        dead = [uid for uid, q in self._incoming.items() if not q or q[-1] < cutoff]
        for uid in dead:
            self._incoming.pop(uid, None)

    # ---------- Исходящие ----------
    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            float(self.outgoing_burst),
            self._tokens + elapsed * self.outgoing_rate,
        )
        self._last_refill = now

    def acquire_outgoing(self, timeout: float = 5.0) -> bool:
        """
        Ждёт, пока появится токен. Возвращает True, если удалось,
        False — если истёк таймаут (тогда лучше пропустить отправку).
        """
        deadline = time.monotonic() + timeout
        while True:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)


def send_with_retry(
    vk,
    *,
    user_id: int,
    message: str,
    random_id: int,
    keyboard: Optional[str] = None,
    limiter: Optional[RateLimiter] = None,
    max_retries: int = 3,
) -> bool:
    """
    Отправляет сообщение с учётом глобального limiter и повторных попыток
    при flood control / too many rps.
    """
    for attempt in range(max_retries):
        if limiter is not None and not limiter.acquire_outgoing():
            # не смогли получить токен — не рискуем злить VK
            return False

        try:
            vk.messages.send(
                user_id=user_id,
                message=message,
                random_id=random_id,
                keyboard=keyboard,
            )
            return True
        except vk_api.exceptions.ApiError as e:
            code = getattr(e, "code", None)
            if code in (6, 9):          # too many rps / flood control
                wait = 1.0 * (attempt + 1)
                print(
                    f"[rate] VK ApiError {code} on user={user_id}, "
                    f"retry in {wait:.1f}s (attempt {attempt + 1}/{max_retries})",
                    flush=True,
                )
                time.sleep(wait)
                continue
            raise
    return False
