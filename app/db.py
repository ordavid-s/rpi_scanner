from __future__ import annotations

import csv
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS gps_fixes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    mode INTEGER,
    lat REAL,
    lon REAL,
    alt REAL,
    speed REAL,
    track REAL,
    sats INTEGER,
    epx REAL,
    epy REAL
);

CREATE TABLE IF NOT EXISTS bluetooth_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    address TEXT NOT NULL,
    name TEXT,
    alias TEXT,
    rssi INTEGER,
    paired INTEGER DEFAULT 0,
    trusted INTEGER DEFAULT 0,
    blocked INTEGER DEFAULT 0,
    connected INTEGER DEFAULT 0,
    uuids TEXT,
    lat REAL,
    lon REAL,
    gps_mode INTEGER,
    gps_ts TEXT
);

CREATE INDEX IF NOT EXISTS idx_bt_ts ON bluetooth_observations(ts DESC);
CREATE INDEX IF NOT EXISTS idx_bt_address ON bluetooth_observations(address);

CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL
);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def log_event(self, level: str, message: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO event_log(ts, level, message) VALUES (?, ?, ?)",
                (utc_now_iso(), level.upper(), message),
            )
            conn.commit()

    def insert_gps_fix(self, fix: Dict) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO gps_fixes(ts, mode, lat, lon, alt, speed, track, sats, epx, epy)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fix.get("time") or utc_now_iso(),
                    fix.get("mode"),
                    fix.get("lat"),
                    fix.get("lon"),
                    fix.get("alt"),
                    fix.get("speed"),
                    fix.get("track"),
                    fix.get("sats"),
                    fix.get("epx"),
                    fix.get("epy"),
                ),
            )
            conn.commit()

    def insert_bt_observation(self, obs: Dict, gps: Optional[Dict] = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO bluetooth_observations(
                    ts, address, name, alias, rssi, paired, trusted, blocked, connected,
                    uuids, lat, lon, gps_mode, gps_ts
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    obs.get("ts") or utc_now_iso(),
                    obs.get("address"),
                    obs.get("name"),
                    obs.get("alias"),
                    obs.get("rssi"),
                    int(bool(obs.get("paired"))),
                    int(bool(obs.get("trusted"))),
                    int(bool(obs.get("blocked"))),
                    int(bool(obs.get("connected"))),
                    ", ".join(obs.get("uuids", [])) if obs.get("uuids") else None,
                    gps.get("lat") if gps else None,
                    gps.get("lon") if gps else None,
                    gps.get("mode") if gps else None,
                    gps.get("time") if gps else None,
                ),
            )
            conn.commit()

    def get_recent_bt(self, limit: int = 100) -> List[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM bluetooth_observations
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return rows

    def get_recent_events(self, limit: int = 50) -> List[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM event_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return rows

    def export_bt_csv(self, output_path: str) -> str:
        with self.connect() as conn, open(output_path, "w", newline="", encoding="utf-8") as f:
            rows = conn.execute(
                "SELECT * FROM bluetooth_observations ORDER BY id DESC"
            ).fetchall()
            writer = csv.writer(f)
            writer.writerow([
                "id", "ts", "address", "name", "alias", "rssi", "paired", "trusted",
                "blocked", "connected", "uuids", "lat", "lon", "gps_mode", "gps_ts"
            ])
            for r in rows:
                writer.writerow([r[k] for k in r.keys()])
        return output_path
