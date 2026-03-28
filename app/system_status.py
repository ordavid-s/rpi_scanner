from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Dict


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def get_system_status() -> Dict:
    temp_c = None
    temp_raw = _read_text("/sys/class/thermal/thermal_zone0/temp")
    if temp_raw.isdigit():
        temp_c = round(int(temp_raw) / 1000.0, 1)

    uptime_seconds = None
    uptime_raw = _read_text("/proc/uptime").split()
    if uptime_raw:
        try:
            uptime_seconds = int(float(uptime_raw[0]))
        except ValueError:
            pass

    disk = shutil.disk_usage("/")

    ip_addr = ""
    try:
        out = subprocess.check_output(
            ["hostname", "-I"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        ip_addr = out.split()[0] if out else ""
    except Exception:  # noqa: BLE001
        pass

    return {
        "temp_c": temp_c,
        "uptime_seconds": uptime_seconds,
        "disk_total_gb": round(disk.total / (1024**3), 2),
        "disk_free_gb": round(disk.free / (1024**3), 2),
        "ip_addr": ip_addr,
        "now": int(time.time()),
    }
