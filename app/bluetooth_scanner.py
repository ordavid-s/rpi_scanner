from __future__ import annotations

import asyncio
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .db import Database
from .gps_reader import GPSReader
from .state import AppState


DEVICE_RE = re.compile(r"^Device\s+([0-9A-F:]{17})\s*(.*)$", re.IGNORECASE)
YESNO_RE = re.compile(r"^(yes|no)$", re.IGNORECASE)


class BluetoothScanner:
    def __init__(
        self,
        db: Database,
        state: AppState,
        gps: GPSReader,
        scan_seconds: int = 8,
        loop_sleep: int = 5,
    ):
        self.db = db
        self.state = state
        self.gps = gps
        self.scan_seconds = scan_seconds
        self.loop_sleep = loop_sleep
        self.enabled = False

    def start(self) -> None:
        self.enabled = True
        self.db.log_event("INFO", "Bluetooth scan requested: start")

    def stop(self) -> None:
        self.enabled = False
        self.state.set_scanner("idle")
        self.db.log_event("INFO", "Bluetooth scan requested: stop")
        self._run_cmd(["bluetoothctl", "scan", "off"], timeout=5, check=False)

    async def run_forever(self) -> None:
        while True:
            if not self.enabled:
                await asyncio.sleep(1)
                continue
            try:
                self.state.set_scanner("running")
                await asyncio.to_thread(self.scan_once)
                await asyncio.sleep(self.loop_sleep)
            except Exception as exc:  # noqa: BLE001
                self.state.set_scanner("error", str(exc))
                self.db.log_event("ERROR", f"Bluetooth scan failed: {exc}")
                await asyncio.sleep(3)

    def scan_once(self) -> None:
        self._run_cmd(["bluetoothctl", "power", "on"], timeout=5)
        self._run_cmd(["bluetoothctl", "scan", "le"], timeout=5, check=False)
        self._run_cmd(["bluetoothctl", "--timeout", str(self.scan_seconds), "scan", "on"], timeout=self.scan_seconds + 5, check=False)
        devices_output = self._run_cmd(["bluetoothctl", "devices"], timeout=10)
        for line in devices_output.splitlines():
            line = line.strip()
            if not line:
                continue
            m = DEVICE_RE.match(line)
            if not m:
                continue
            address = m.group(1)
            fallback_name = m.group(2).strip() or None
            obs = self._read_device_info(address, fallback_name)
            self.db.insert_bt_observation(obs, gps=self.gps.latest_fix)
        self.state.bluetooth_last_run = datetime.now(timezone.utc).isoformat()

    def _read_device_info(self, address: str, fallback_name: Optional[str]) -> Dict:
        text = self._run_cmd(["bluetoothctl", "info", address], timeout=8, check=False)
        data: Dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "address": address,
            "name": fallback_name,
            "alias": fallback_name,
            "uuids": [],
        }
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "name":
                data["name"] = value
            elif key == "alias":
                data["alias"] = value
            elif key == "rssi":
                try:
                    data["rssi"] = int(value)
                except ValueError:
                    pass
            elif key in {"paired", "trusted", "blocked", "connected"}:
                data[key] = value.lower() == "yes"
            elif key == "uuid":
                data.setdefault("uuids", []).append(value)
        return data

    def _run_cmd(self, cmd: List[str], timeout: int = 10, check: bool = True) -> str:
        env = os.environ.copy()
        env.setdefault("LC_ALL", "C")
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stdout}")
        return proc.stdout
