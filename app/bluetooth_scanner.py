from __future__ import annotations

import asyncio
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from .db import Database
from .gps_reader import GPSReader
from .state import AppState


DEVICE_RE = re.compile(
    r"Device\s+(?P<addr>[0-9A-F:]{17})\s*(?P<name>.*)$",
    re.IGNORECASE,
)


class BluetoothScanner:
    def __init__(
        self,
        db: Database,
        state: AppState,
        gps_reader: GPSReader,
        scan_seconds: int = 10,   # kept for compatibility; not used in continuous mode
        loop_sleep: int = 5,      # kept for compatibility; not used in continuous mode
        adapter: str = "",
        dedup_seconds: int = 30,
    ):
        self.db = db
        self.state = state
        self.gps_reader = gps_reader
        self.scan_seconds = scan_seconds
        self.loop_sleep = loop_sleep
        self.adapter = adapter
        self.dedup_seconds = dedup_seconds

        self.enabled = False
        self.proc: Optional[subprocess.Popen] = None
        self.reader_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.last_seen_logged: dict[str, float] = {}

    def start(self) -> None:
        if self.enabled:
            return
        self.enabled = True
        self.stop_event.clear()
        self.db.log_event("INFO", "Bluetooth continuous scan requested: start")

    def stop(self) -> None:
        self.enabled = False
        self.stop_event.set()
        self._stop_scan_process()
        self.state.set_scanner("idle")
        self.db.log_event("INFO", "Bluetooth continuous scan requested: stop")

    async def run_forever(self) -> None:
        while True:
            if not self.enabled:
                await asyncio.sleep(1)
                continue

            try:
                self.state.set_scanner("running")
                await asyncio.to_thread(self._run_continuous_session)
            except Exception as exc:
                self.state.set_scanner("error", str(exc))
                self.db.log_event("ERROR", f"Bluetooth scan failed: {exc}")
                await asyncio.sleep(3)

    def validate_adapter(self) -> None:
        out = self._run_btctl_script("list\nquit\n", timeout=10, check=False)
        if self.adapter and self.adapter not in out:
            raise RuntimeError(
                f"Bluetooth adapter {self.adapter} not found. bluetoothctl list output:\n{out}"
            )

    def _run_continuous_session(self) -> None:
        self.validate_adapter()

        env = os.environ.copy()
        env["LC_ALL"] = "C"

        self.proc = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )

        try:
            self._send("select " + self.adapter)
            self._send("power on")
            self._send("scan on")

            self.db.log_event("INFO", f"Bluetooth continuous scan started on adapter {self.adapter}")

            self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.reader_thread.start()

            while self.enabled and not self.stop_event.is_set():
                time.sleep(1)

        finally:
            self._stop_scan_process()

    def _reader_loop(self) -> None:
        assert self.proc is not None
        assert self.proc.stdout is not None

        for raw_line in self.proc.stdout:
            if self.stop_event.is_set():
                break

            line = raw_line.strip()
            if not line:
                continue

            self._handle_scan_line(line)

        self.state.bluetooth_last_run = datetime.now(timezone.utc).isoformat()

    def _handle_scan_line(self, line: str) -> None:
        """
        Handle live bluetoothctl output while scan is running.
        Typical lines can contain '[NEW] Device AA:BB:... Name'
        or '[CHG] Device ... RSSI: ...', etc.
        """
        m = DEVICE_RE.search(line)
        if not m:
            return

        address = m.group("addr")
        fallback_name = (m.group("name") or "").strip()

        now_ts = time.time()
        last_ts = self.last_seen_logged.get(address, 0.0)
        if now_ts - last_ts < self.dedup_seconds:
            return

        self.last_seen_logged[address] = now_ts

        try:
            obs = self._read_device_info(address, fallback_name=fallback_name)
        except Exception:
            obs = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "address": address,
                "name": fallback_name,
                "alias": fallback_name,
                "uuids": [],
            }

        gps = self.gps_reader.latest_fix
        self.db.insert_bt_observation(obs, gps=gps)

    def _read_device_info(self, address: str, fallback_name: Optional[str]) -> Dict:
        text = self._run_btctl_script(
            f"select {self.adapter}\ninfo {address}\nquit\n",
            timeout=10,
            check=False,
        )

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

    def _send(self, command: str) -> None:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("bluetoothctl process is not running")
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()

    def _stop_scan_process(self) -> None:
        if self.proc:
            try:
                if self.proc.stdin:
                    try:
                        self.proc.stdin.write("scan off\n")
                        self.proc.stdin.write("quit\n")
                        self.proc.stdin.flush()
                    except Exception:
                        pass

                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
            finally:
                self.proc = None

    def _run_btctl_script(self, script_text: str, timeout: int = 20, check: bool = True) -> str:
        env = os.environ.copy()
        env["LC_ALL"] = "C"

        proc = subprocess.run(
            ["bluetoothctl"],
            input=script_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
        )

        if check and proc.returncode != 0:
            raise RuntimeError(
                f"Command failed: bluetoothctl\nstdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
            )

        return proc.stdout
