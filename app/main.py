from __future__ import annotations

import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .bluetooth_scanner import BluetoothScanner
from .db import Database
from .gps_reader import GPSReader
from .state import AppState
from .system_status import get_system_status


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

APP_SECRET = os.getenv("APP_SECRET", "change-me")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
DB_PATH = os.getenv("DB_PATH", str(PROJECT_DIR / "data" / "app.db"))
GPSD_HOST = os.getenv("GPSD_HOST", "127.0.0.1")
GPSD_PORT = int(os.getenv("GPSD_PORT", "2947"))
SCAN_SECONDS = int(os.getenv("SCAN_SECONDS", "8"))
SCAN_LOOP_SLEEP = int(os.getenv("SCAN_LOOP_SLEEP", "5"))
MAX_ROWS_DASHBOARD = int(os.getenv("MAX_ROWS_DASHBOARD", "50"))
BT_ADAPTER = os.getenv("BT_ADAPTER", "hci0")

state = AppState()
db = Database(DB_PATH)
gps = GPSReader(db=db, state=state, host=GPSD_HOST, port=GPSD_PORT)
scanner = BluetoothScanner(
    db=db,
    state=state,
    gps_reader=gps,
    scan_seconds=SCAN_SECONDS,
    loop_sleep=SCAN_LOOP_SLEEP,
    adapter=BT_ADAPTER,
)

gps_task: Optional[asyncio.Task] = None
scanner_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global gps_task, scanner_task
    db.log_event("INFO", "App startup")
    gps_task = asyncio.create_task(gps.run_forever())
    scanner_task = asyncio.create_task(scanner.run_forever())
    try:
        yield
    finally:
        db.log_event("INFO", "App shutdown")
        for task in (gps_task, scanner_task):
            if task:
                task.cancel()
        await asyncio.gather(*(t for t in (gps_task, scanner_task) if t), return_exceptions=True)


app = FastAPI(title="BT GPS Panel", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


def require_auth(request: Request) -> None:
    if not request.session.get("auth"):
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    if not request.session.get("auth"):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "login.html", {"error": ""})


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, password: str = Form(...)):
    if secrets.compare_digest(password, ADMIN_PASSWORD):
        request.session["auth"] = True
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return TEMPLATES.TemplateResponse(
        request,
        "login.html",
        {"error": "Invalid password"},
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, _: None = Depends(require_auth)):
    return TEMPLATES.TemplateResponse(request, "dashboard.html", {})


@app.post("/api/scan/start")
def api_start_scan(_: None = Depends(require_auth)):
    scanner.start()
    return {"ok": True, "status": "running"}


@app.post("/api/scan/stop")
def api_stop_scan(_: None = Depends(require_auth)):
    scanner.stop()
    return {"ok": True, "status": "idle"}


@app.get("/api/status")
def api_status(_: None = Depends(require_auth)):
    return {
        "app": state.snapshot(),
        "system": get_system_status(),
    }


@app.get("/api/recent")
def api_recent(_: None = Depends(require_auth)):
    rows = db.get_recent_bt(MAX_ROWS_DASHBOARD)
    return {"items": [dict(r) for r in rows]}


@app.get("/api/events")
def api_events(_: None = Depends(require_auth)):
    rows = db.get_recent_events(20)
    return {"items": [dict(r) for r in rows]}


@app.get("/export/bluetooth.csv")
def export_bt(_: None = Depends(require_auth)):
    out_path = str(PROJECT_DIR / "data" / "bluetooth_export.csv")
    db.export_bt_csv(out_path)
    return FileResponse(out_path, media_type="text/csv", filename="bluetooth_export.csv")
