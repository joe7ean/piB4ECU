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

class AppState:
    def __init__(self):
        self.engine = ECUState()
        self.abs = ECUState() # Optional for later
        self.global_tick = 0

state = AppState()
clients: set[WebSocket] = set()
ecu_engine: Optional[KW1281] = None
ecu_abs: Optional[KW1281] = None


# ── ECU polling loop ───────────────────────────────────────────────────────────

async def ecu_poll_loop():
    global ecu_engine
    
    # Wir pollen erstmal nur Engine, ABS kann später als zweiter Task dazu
    while True:
        try:
            if DEMO_MODE:
                await _demo_tick()
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # ── Verbinden ──────────────────────────────────────────────────────
            if not state.engine.connected:
                log.info("Verbinde mit Engine ECU...")
                ecu_engine = KW1281(SERIAL_PORT)
                ident = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: ecu_engine.connect(ECU_ENGINE)
                )
                state.engine.ident = ident
                state.engine.connected = True
                state.engine.error = None
                log.info(f"Engine ECU verbunden: {ident}")

            # ── Messwertblöcke lesen ───────────────────────────────────────────
            # Für Mono-Motronic 1.8l ABS/ADZ sind Block 0, 1 und 2 relevant. 
            # Block 0 liefert Rohdaten, Block 1 und 2 die umgerechneten Werte.
            data = {}
            for block_num in [1, 2]:
                group = await asyncio.get_event_loop().run_in_executor(
                    None, lambda b=block_num: ecu_engine.read_measurement_block(b)
                )
                for label, value, unit in group.values:
                    data[label] = {"value": value, "unit": unit}

            state.engine.last_data = data
            state.engine.tick += 1
            state.global_tick += 1
            await _broadcast()

        except KW1281Error as e:
            log.warning(f"Engine ECU Fehler: {e} — Neuverbindung in 3s")
            state.engine.connected = False
            state.engine.error = str(e)
            if ecu_engine:
                try: ecu_engine.disconnect()
                except: pass
            await _broadcast_error(str(e), "engine")
            await asyncio.sleep(3)

        except Exception as e:
            log.error(f"Unerwarteter Fehler: {e}")
            state.engine.connected = False
            state.engine.error = str(e)
            await asyncio.sleep(5)

        await asyncio.sleep(POLL_INTERVAL)


async def _demo_tick():
    """Simulierte Daten für Entwicklung ohne KKL-Adapter."""
    import random, math
    t = state.global_tick
    state.global_tick += 1
    state.engine.tick += 1

    rpm_base = 820 + math.sin(t * 0.1) * 60
    
    # Simuliere Operating Status Bitmaske
    # Bit 2 (Leerlauf) und Bit 7 (Lambda aktiv)
    op_status = 0b01000010 if rpm_base < 1000 else 0b01000000
    
    state.engine.last_data = {
        "Drehzahl":              {"value": round(rpm_base + random.uniform(-30, 30)), "unit": "U/min"},
        "Kühlmitteltemperatur":  {"value": round(87 + random.uniform(-2, 2)),          "unit": "°C"},
        "Spannung":              {"value": round(13.8 + random.uniform(-0.2, 0.2), 1), "unit": "V"},
        "Lambda":                {"value": round(1.0 + random.uniform(-0.05, 0.05), 3),"unit": "λ"},
        "Einspritzzeit":         {"value": round(1.2 + random.uniform(-0.1, 0.1), 2) if rpm_base < 1000 else 2.5,  "unit": "ms"},
        "Ansauglufttemperatur":  {"value": round(32 + random.uniform(-1, 1)),           "unit": "°C"},
        "Betriebszustand":       {"value": op_status, "unit": "bit"},
    }
    state.engine.connected = True
    state.engine.ident = "DEMO · 8A0 907 311 K · 0001"
    
    if not state.engine.fault_codes:
        state.engine.fault_codes = [
            {"code": "P0130", "desc": "Lambdasonde — Signal außerhalb Bereich", "status": "gespeichert"},
        ]
        
    await _broadcast()


async def _broadcast():
    msg = json.dumps({
        "type":    "data",
        "tick":    state.global_tick,
        "ts":      datetime.now().isoformat(),
        "engine": {
            "connected": state.engine.connected,
            "ident":   state.engine.ident,
            "data":    state.engine.last_data,
            "faults":  state.engine.fault_codes,
            "tick":    state.engine.tick
        },
        "abs": {
            "connected": state.abs.connected,
            "ident":   state.abs.ident,
            "data":    state.abs.last_data,
            "faults":  state.abs.fault_codes,
            "tick":    state.abs.tick
        }
    })
    dead = set()
    for ws in clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    clients.difference_update(dead)


async def _broadcast_error(msg: str, ecu_type: str = "engine"):
    payload = json.dumps({"type": "error", "ecu": ecu_type, "message": msg})
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
    if ecu_engine:
        try: ecu_engine.disconnect()
        except: pass
    if ecu_abs:
        try: ecu_abs.disconnect()
        except: pass

app = FastAPI(title="Passat B4 ECU Dashboard", lifespan=lifespan)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    log.info(f"Client verbunden: {ws.client}")
    try:
        # Sofort aktuellen Stand senden
        if state.engine.last_data or state.abs.last_data:
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
        "engine_connected": state.engine.connected,
        "engine_ident":     state.engine.ident,
        "global_tick":      state.global_tick,
        "clients":          len(clients),
    }


@app.post("/api/read-faults")
async def read_faults(ecu: str = "engine"):
    """Manuelles Auslesen des Fehlerspeichers (verhindert UI-Lag beim normalen Polling)"""
    target_ecu = ecu_engine if ecu == "engine" else ecu_abs
    target_state = state.engine if ecu == "engine" else state.abs
    
    if not target_state.connected or not target_ecu:
        return {"ok": False, "error": f"ECU '{ecu}' nicht verbunden"}
        
    if DEMO_MODE:
        return {"ok": True, "faults": target_state.fault_codes}
        
    try:
        faults = await asyncio.get_event_loop().run_in_executor(None, target_ecu.read_fault_codes)
        target_state.fault_codes = [
            {"code": f"P{f.code:04X}", "desc": f.description, "status": f.status}
            for f in faults
        ]
        await _broadcast()
        return {"ok": True, "faults": target_state.fault_codes}
    except KW1281Error as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/clear-faults")
async def clear_faults(ecu: str = "engine"):
    target_ecu = ecu_engine if ecu == "engine" else ecu_abs
    target_state = state.engine if ecu == "engine" else state.abs
    
    if not target_state.connected or not target_ecu:
        return {"ok": False, "error": f"ECU '{ecu}' nicht verbunden"}
        
    if DEMO_MODE:
        target_state.fault_codes = []
        await _broadcast()
        return {"ok": True}
        
    try:
        await asyncio.get_event_loop().run_in_executor(None, target_ecu.clear_fault_codes)
        target_state.fault_codes = []
        await _broadcast()
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
