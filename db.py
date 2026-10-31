import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from models import Observation, Prediction


class Database:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.init()

    def init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                wait_min INTEGER,
                lat REAL,
                lon REAL,
                jam_length_m REAL,
                jam_level INTEGER,
                raw_json TEXT,
                user_hash TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_obs_ts
            ON observations(ts_utc);

            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                status TEXT NOT NULL,
                p_closed REAL NOT NULL,
                expected_wait_min INTEGER,
                expected_open_at TEXT,
                confidence REAL NOT NULL,
                details_json TEXT
            );
            """
        )
        self.conn.commit()

    def add_observation(self, obs: Observation) -> None:
        self.conn.execute(
            """
            INSERT INTO observations (
                ts_utc, source, status, wait_min, lat, lon,
                jam_length_m, jam_level, raw_json, user_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                obs.ts.astimezone(timezone.utc).isoformat(),
                obs.source,
                obs.status,
                obs.wait_min,
                obs.lat,
                obs.lon,
                obs.jam_length_m,
                obs.jam_level,
                json.dumps(obs.raw, ensure_ascii=False) if obs.raw else None,
                obs.user_hash,
            ),
        )
        self.conn.commit()

    def recent_observations(self, since: datetime, limit: int = 200) -> list[Observation]:
        rows = self.conn.execute(
            """
            SELECT * FROM observations
            WHERE ts_utc >= ?
            ORDER BY ts_utc DESC
            LIMIT ?
            """,
            (since.astimezone(timezone.utc).isoformat(), limit),
        ).fetchall()
        return [self._row_to_observation(r) for r in rows]

    def add_prediction(self, pred: Prediction, now: datetime) -> None:
        self.conn.execute(
            """
            INSERT INTO predictions (
                ts_utc, status, p_closed, expected_wait_min,
                expected_open_at, confidence, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now.astimezone(timezone.utc).isoformat(),
                pred.status,
                pred.p_closed,
                pred.expected_wait_min,
                pred.expected_open_at.astimezone(timezone.utc).isoformat()
                if pred.expected_open_at
                else None,
                pred.confidence,
                json.dumps(pred.details, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    @staticmethod
    def _row_to_observation(row: sqlite3.Row) -> Observation:
        return Observation(
            ts=datetime.fromisoformat(row["ts_utc"]),
            source=row["source"],
            status=row["status"],
            wait_min=row["wait_min"],
            lat=row["lat"],
            lon=row["lon"],
            jam_length_m=row["jam_length_m"],
            jam_level=row["jam_level"],
            raw=json.loads(row["raw_json"]) if row["raw_json"] else None,
            user_hash=row["user_hash"],
        )
