from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, Optional


@dataclass
class AppState:
    scanner_status: str = "idle"
    scanner_error: str = ""

    gps_status: str = "searching"   # searching | fix | retrying
    gps_error: str = ""
    latest_gps: Dict[str, Any] = field(default_factory=dict)

    bluetooth_last_run: Optional[str] = None
    lock: Lock = field(default_factory=Lock)

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "scanner_status": self.scanner_status,
                "scanner_error": self.scanner_error,
                "gps_status": self.gps_status,
                "gps_error": self.gps_error,
                "latest_gps": dict(self.latest_gps),
                "bluetooth_last_run": self.bluetooth_last_run,
            }

    def set_scanner(self, status: str, error: str = "") -> None:
        with self.lock:
            self.scanner_status = status
            self.scanner_error = error

    def set_gps(
        self,
        status: str,
        gps: Optional[Dict[str, Any]] = None,
        error: str = "",
    ) -> None:
        with self.lock:
            self.gps_status = status
            self.gps_error = error
            if gps is not None:
                self.latest_gps = gps
