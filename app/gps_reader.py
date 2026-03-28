from __future__ import annotations

import asyncio
import json
import socket
from datetime import datetime, timezone
from typing import Dict, Optional

from .db import Database
from .state import AppState


class GPSReader:
    def __init__(self, db: Database, state: AppState, host: str = "127.0.0.1", port: int = 2947):
        self.db = db
        self.state = state
        self.host = host
        self.port = port
        self._latest_fix: Optional[Dict] = None

    @property
    def latest_fix(self) -> Optional[Dict]:
        return self._latest_fix

    async def run_forever(self) -> None:
        while True:
            try:
                await self._read_once()
            except Exception as exc:  # noqa: BLE001
                self.state.set_gps("no_fix", gps=self._latest_fix or {}, error=str(exc))
                self.db.log_event("ERROR", f"GPS loop error: {exc}")
                await asyncio.sleep(3)

    async def _read_once(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=5)
        try:
            sock.settimeout(5)
            sock.sendall(b'?WATCH={"enable":true,"json":true}\n')
            f = sock.makefile("r", encoding="utf-8", errors="replace")
            while True:
                line = f.readline()
                if not line:
                    raise RuntimeError("gpsd closed connection")
                line = line.strip()
                if not line:
                    continue
                msg = json.loads(line)
                if msg.get("class") != "TPV":
                    continue
                fix = self._parse_tpv(msg)
                if fix is None:
                    continue
                self._latest_fix = fix
                if fix["mode"] >= 2 and fix.get("lat") is not None and fix.get("lon") is not None:
                    self.state.set_gps("fix", gps=fix)
                    self.db.insert_gps_fix(fix)
                else:
                    self.state.set_gps("stale", gps=fix)
        finally:
            sock.close()

    def _parse_tpv(self, msg: Dict) -> Optional[Dict]:
        time_str = msg.get("time") or datetime.now(timezone.utc).isoformat()
        return {
            "time": time_str,
            "mode": int(msg.get("mode", 0)),
            "lat": msg.get("lat"),
            "lon": msg.get("lon"),
            "alt": msg.get("altMSL") or msg.get("altHAE") or msg.get("alt"),
            "speed": msg.get("speed"),
            "track": msg.get("track"),
            "sats": msg.get("satellites_used"),
            "epx": msg.get("epx"),
            "epy": msg.get("epy"),
        }
