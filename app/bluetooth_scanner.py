from __future__ import annotations

import asyncio
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Dict, List, Optional
import time

from .db import Database
from .gps_reader import GPSReader
from .state import AppState


DEVICE_RE = re.compile(
    r"^Device\s+(?P<addr>[0-9A-F:]{17})\s*(?P<name>.*)$",
    re.IGNORECASE,
)

YESNO_RE = re.compile(r"^(yes|no)$", re.IGNORECASE)


class BluetoothScanner:
    def __init__(self, db, state, gps_reader, scan_seconds=10, loop_sleep=5, adapter="hci0"):
        self.db = db
        self.state = state
        self.gps_reader = gps_reader
        self.scan_seconds = scan_seconds
        self.loop_sleep = loop_sleep
        self.adapter = adapter
        self.enabled = False

    def _btctl(self, command_text: str, timeout: int = 20, check: bool = True) -> str:
        """
        Run bluetoothctl while explicitly selecting the configured adapter.
        """
        full_input = f"select {self.adapter}\n{command_text}\nquit\n"
        return self._run_cmd(
            ["bluetoothctl"],
            timeout=timeout,
            check=check,
            input_text=full_input,
        )
    
    def start(self) -> None:
        self.enabled = True
        self.db.log_event("INFO", "Bluetooth scan requested: start")

    def stop(self) -> None:
        self.enabled = False
        self.state.set_scanner("idle")
        self.db.log_event("INFO", "Bluetooth scan requested: stop")
        self._btctl("scan off", timeout=10, check=False)

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

    def validate_adapter(self):
        out = self._btctl("list", timeout=10, check=False)
        if self.adapter not in out:
            raise RuntimeError(f"Bluetooth adapter {self.adapter} not found. bluetoothctl list output:\n{out}")
    
    def scan_once(self):
        self._btctl("power on", timeout=10)
        self._btctl("menu scan\ntransport le\nback", timeout=10, check=False)
        self._btctl("scan on", timeout=10, check=False)
    
        time.sleep(self.scan_seconds)
    
        self._btctl("scan off", timeout=10, check=False)
        devices_out = self._btctl("devices", timeout=10)
    
        gps = self.gps_reader.latest_fix
    
        for line in devices_out.splitlines():
            m = DEVICE_RE.match(line.strip())
            if not m:
                continue
    
            address = m.group("addr")
            fallback_name = (m.group("name") or "").strip()
            obs = self._read_device_info(address, fallback_name=fallback_name)
            self.db.insert_bt_observation(obs, gps=gps)
    
        self.state.bluetooth_last_run = datetime.now(timezone.utc).isoformat()

    def _read_device_info(self, address: str, fallback_name: Optional[str]) -> Dict:
        text = self._btctl(f"info {address}", timeout=10, check=False)
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

    def _run_cmd(self, cmd, timeout=20, check=True, input_text=None):
        env = os.environ.copy()
        env["LC_ALL"] = "C"
    
        proc = subprocess.run(
            cmd,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"Command failed: {' '.join(cmd)}\n"
                f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
            )
    
        return proc.stdout
