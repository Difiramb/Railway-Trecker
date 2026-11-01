from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Any


@dataclass
class Observation:
    ts: datetime
    source: str                  # user / yandex / manual
    status: str                  # closed / open / unknown
    wait_min: Optional[int] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    jam_length_m: Optional[float] = None
    jam_level: Optional[int] = None
    raw: Optional[dict] = None
    user_hash: Optional[str] = None
    plausibility: float = 1.0     # ← новое поле


@dataclass
class Prediction:
    status: str                  # closed / open / unknown
    p_closed: float
    expected_wait_min: Optional[int]
    expected_open_at: Optional[datetime]
    confidence: float
    details: dict[str, Any]
