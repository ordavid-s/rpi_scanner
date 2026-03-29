from __future__ import annotations

import asyncio
import json
import socket
from datetime import datetime, timezone
from typing import Dict, Optional

from .db import Database
from .state import AppState


class GPSReader:
    def __init__(
        self,
        db: Database,
        state: AppState,
        host: str = "127.0.0.1",
        port: int = 2947,
        connect_timeout: int = 5,
        read_timeout: int = 10,
        retry_delay: int = 3,
    ):
        self.db = db
        self.state = state
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.retry_delay = retry_delay
        self._latest_fix: Optional[Dict] = None
        self._last_error_logged: Optional[str] = None

    @property
    def latest_fix(self) -> Optional[Dict]:
        return self._latest_fix

    async def run_forever(self) -> None:
        while True:
            try:
                self.state.set_gps(
                    "searching",
                    gps=self._latest_fix or {},
                    error="Connecting to gpsd...",
                )
                await self._read_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
                self.state.set_gps(
                    "retrying",
                    gps=self._latest_fix or {},
                    error=f"GPS reconnecting: {err}",
                )
                if err != self._last_error_logged:
                    self.db.log_event("WARNING", f"GPS reconnecting after error: {err}")
                    self._last_error_logged = err
                await asyncio.sleep(self.retry_delay)

    async def _read_once(self) -> None:
        sock = socket.create_connection(
            (self.host, self.port),
            timeout=self.connect_timeout,
        )
        try:
            sock.settimeout(self.read_timeout)
            sock.sendall(b'?WATCH={"enable":true,"json":true}\n')
            f = sock.makefile("r", encoding="utf-8", errors="replace")

            while True:
                try:
                    line = f.readline()
                except socket.timeout:
                    raise RuntimeError("timed out waiting for GPS data")

                if not line:
                    raise RuntimeError("gpsd closed connection")

                line = line.strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if msg.get("class") != "TPV":
                    continue

                fix = self._parse_tpv(msg)
                if fix is None:
                    continue

                self._latest_fix = fix
                self._last_error_logged = None

                mode = fix["mode"]
                has_coords = fix.get("lat") is not None and fix.get("lon") is not None

                if mode >= 2 and has_coords:
                    self.state.set_gps("fix", gps=fix, error="")
                    self.db.insert_gps_fix(fix)
                else:
                    self.state.set_gps(
                        "searching",
                        gps=fix,
                        error="Waiting for valid GPS fix...",
                    )
        finally:
            try:
                sock.close()
            except Exception:
                pass

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
