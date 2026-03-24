"""
ECU WebSocket Server — Raspberry Pi Zero 2W
Starte mit: python server.py

iPhone verbindet sich via WLAN: http://<raspi-ip>:8000
Dashboard läuft im Safari — keine App nötig.
"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from kw1281 import KW1281, ECU_ENGINE, KW1281Error

# ── Config ─────────────────────────────────────────────────────────────────────
SERIAL_PORT      = "/dev/ttyUSB0"  # KKL USB adapter
##SERIAL_PORT      = "/dev/serial/by-id/usb-FTDI_USB__-__Serial_Cable_12345678-if00-port0"   # KKL USB adapter
POLL_INTERVAL    = 0.8              # Sekunden zwischen ECU-Abfragen
FAULT_INTERVAL   = 30              # Fehlerspeicher alle N Sekunden lesen
DEMO_MODE        = False            # True = simulierte Daten, kein KKL nötig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("server")


# ── State ──────────────────────────────────────────────────────────────────────
class ECUState:
    def __init__(self):
        self.connected   = False
        self.ident       = ""
        self.last_data   = {}
        self.fault_codes = []
        self.error       = None
        self.tick        = 0


state = ECUState()
clients: set[WebSocket] = set()
ecu: Optional[KW1281] = None


# ── ECU polling loop ───────────────────────────────────────────────────────────

async def ecu_poll_loop():
    global ecu
    last_fault_read = 0

    while True:
        try:
            if DEMO_MODE:
                await _demo_tick()
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # ── Verbinden ──────────────────────────────────────────────────────
            if not state.connected:
                log.info("Verbinde mit ECU...")
                ecu = KW1281(SERIAL_PORT)
                ident = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: ecu.connect(ECU_ENGINE)
                )
                state.ident = ident
                state.connected = True
                state.error = None
                log.info(f"ECU verbunden: {ident}")

            # ── Messwertblöcke lesen ───────────────────────────────────────────
            data = {}
            for block_num in [1, 2, 3]:
                group = await asyncio.get_event_loop().run_in_executor(
                    None, lambda b=block_num: ecu.read_measurement_block(b)
                )
                for label, value, unit in group.values:
                    data[label] = {"value": value, "unit": unit}

            # ── Fehlerspeicher periodisch lesen ───────────────────────────────
            now = time.time()
            if now - last_fault_read > FAULT_INTERVAL:
                faults = await asyncio.get_event_loop().run_in_executor(
                    None, ecu.read_fault_codes
                )
                state.fault_codes = [
                    {"code": f"P{f.code:04X}", "desc": f.description, "status": f.status}
                    for f in faults
                ]
                last_fault_read = now

            state.last_data = data
            state.tick += 1
            await _broadcast()

        except KW1281Error as e:
            log.warning(f"ECU Fehler: {e} — Neuverbindung in 3s")
            state.connected = False
            state.error = str(e)
            if ecu:
                try: ecu.disconnect()
                except: pass
            await _broadcast_error(str(e))
            await asyncio.sleep(3)

        except Exception as e:
            log.error(f"Unerwarteter Fehler: {e}")
            state.connected = False
            state.error = str(e)
            await asyncio.sleep(5)

        await asyncio.sleep(POLL_INTERVAL)


async def _demo_tick():
    """Simulierte Daten für Entwicklung ohne KKL-Adapter."""
    import random, math
    t = state.tick
    state.tick += 1

    rpm_base = 820 + math.sin(t * 0.1) * 60
    state.last_data = {
        "Drehzahl":              {"value": round(rpm_base + random.uniform(-30, 30)), "unit": "U/min"},
        "Kühlmitteltemperatur":  {"value": round(87 + random.uniform(-2, 2)),          "unit": "°C"},
        "Spannung":              {"value": round(13.8 + random.uniform(-0.2, 0.2), 1), "unit": "V"},
        "Lambda":                {"value": round(1.0 + random.uniform(-0.05, 0.05), 3),"unit": "λ"},
        "Geschwindigkeit":       {"value": max(0, round(random.uniform(0, 15))),        "unit": "km/h"},
        "Zündwinkel":            {"value": round(14 + random.uniform(-2, 2), 1),        "unit": "°KW"},
        "Einspritzzeit":         {"value": round(3.2 + random.uniform(-0.3, 0.3), 2),  "unit": "ms"},
        "Drosselklappe":         {"value": round(18 + random.uniform(-5, 5), 1),        "unit": "%"},
        "Ansauglufttemperatur":  {"value": round(22 + random.uniform(-1, 1)),           "unit": "°C"},
    }
    state.connected = True
    state.ident = "DEMO · 1HM 906 258 · 0001"
    if not state.fault_codes:
        state.fault_codes = [
            {"code": "P0130", "desc": "Lambdasonde — Signal außerhalb Bereich", "status": "gespeichert"},
        ]
    await _broadcast()


async def _broadcast():
    msg = json.dumps({
        "type":    "data",
        "tick":    state.tick,
        "ts":      datetime.now().isoformat(),
        "connected": state.connected,
        "ident":   state.ident,
        "data":    state.last_data,
        "faults":  state.fault_codes,
    })
    dead = set()
    for ws in clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    clients.difference_update(dead)


async def _broadcast_error(msg: str):
    payload = json.dumps({"type": "error", "message": msg})
    dead = set()
    for ws in clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    clients.difference_update(dead)


# ── FastAPI app ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(ecu_poll_loop())
    yield
    if ecu:
        try: ecu.disconnect()
        except: pass

app = FastAPI(title="Passat B4 ECU Dashboard", lifespan=lifespan)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    log.info(f"Client verbunden: {ws.client}")
    try:
        # Sofort aktuellen Stand senden
        if state.last_data:
            await _broadcast()
        while True:
            # Ping-Pong halten die Verbindung offen
            await ws.receive_text()
    except WebSocketDisconnect:
        log.info(f"Client getrennt: {ws.client}")
    finally:
        clients.discard(ws)


@app.get("/api/status")
def api_status():
    return {
        "connected": state.connected,
        "ident":     state.ident,
        "tick":      state.tick,
        "error":     state.error,
        "clients":   len(clients),
    }


@app.post("/api/clear-faults")
async def clear_faults():
    if not state.connected or not ecu:
        return {"ok": False, "error": "ECU nicht verbunden"}
    try:
        await asyncio.get_event_loop().run_in_executor(None, ecu.clear_fault_codes)
        state.fault_codes = []
        return {"ok": True}
    except KW1281Error as e:
        return {"ok": False, "error": str(e)}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Liefert das Dashboard — öffne auf iPhone in Safari."""
    with open("dashboard.html", "r") as f:
        return f.read()


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",   # erreichbar im lokalen WLAN
        port=8000,
        log_level="info",
        reload=False,
    )
