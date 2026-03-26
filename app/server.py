"""
ECU WebSocket Server — Raspberry Pi Zero 2W
Starte mit: python app/server.py

iPhone verbindet sich via WLAN: http://<raspi-ip>:8000
Dashboard läuft im Safari — keine App nötig.
"""

import asyncio
import json
import logging
import math
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from kw1281 import KW1281, ECU_ENGINE, KW1281Error

# ── Config ─────────────────────────────────────────────────────────────────────
_BASE_DIR = Path(__file__).resolve().parent
SERIAL_PORT      = "/dev/ttyUSB0"  # KKL USB adapter
##SERIAL_PORT      = "/dev/serial/by-id/usb-FTDI_USB__-__Serial_Cable_12345678-if00-port0"   # KKL USB adapter
POLL_INTERVAL    = 0.8              # Sekunden zwischen ECU-Abfragen
FAULT_INTERVAL   = 30              # Fehlerspeicher alle N Sekunden lesen
DEMO_MODE        = False            # True = simulierte Daten, kein KKL nötig
# KW1281-Handshake: mehrere Versuche; optionales Diagnose-Log via ENV
ECU_CONNECT_ATTEMPTS = int(os.environ.get("ECU_CONNECT_ATTEMPTS", "10"))
ECU_DIAG_LOG = os.environ.get("ECU_DIAG_LOG")

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
        self.gps_speed_kmh: Optional[float] = None
        self.gps_speed_ts = 0.0
        self.trip = {
            "distance_km": 0.0,
            "fuel_l": 0.0,
            "drive_time_s": 0.0,
            "avg_speed_kmh": None,
            "avg_l_per_100km": None,
            "live_lph": None,
            "live_l_per_100km": None,
            "speed_kmh": None,
            "speed_source": "N/A",
        }
        self.calibration = {
            "k_estimate": 0.0011,
            "learn_samples": 0,
            "last_source": "none",
            "last_observed_liters": None,
            "last_ratio": None,
            "tank_level_est_l": None,
            "status": "standard",
        }
        self._trip_last_ts = time.time()

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
                log.info("Verbinde mit Engine ECU (%s Versuche)...", ECU_CONNECT_ATTEMPTS)
                ecu_engine = KW1281(SERIAL_PORT)
                ident = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: ecu_engine.connect(
                        ECU_ENGINE,
                        max_attempts=ECU_CONNECT_ATTEMPTS,
                        diagnostic_log_path=ECU_DIAG_LOG,
                    ),
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
            _update_trip_state(data)
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
            await _broadcast_error(f"Systemfehler: {e}", "engine")
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
        "Geschwindigkeit":       {"value": max(0, round(35 + math.sin(t * 0.05) * 20, 1)), "unit": "km/h"},
        "Ansauglufttemperatur":  {"value": round(32 + random.uniform(-1, 1)),           "unit": "°C"},
        "Betriebszustand":       {"value": op_status, "unit": "bit"},
    }
    _update_trip_state(state.engine.last_data)
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
            "trip":    state.trip,
            "calibration": state.calibration,
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


def _get_speed_kmh(data: dict) -> tuple[Optional[float], str]:
    ecu_speed = data.get("Geschwindigkeit", {}).get("value")
    if isinstance(ecu_speed, (int, float)) and ecu_speed >= 0:
        return float(ecu_speed), "ECU"
    # Use GPS if updated recently.
    if state.gps_speed_kmh is not None and (time.time() - state.gps_speed_ts) <= 5.0:
        return float(state.gps_speed_kmh), "GPS"
    return None, "N/A"


def _update_trip_state(data: dict):
    now = time.time()
    dt = max(0.0, min(now - state._trip_last_ts, 2.0))
    state._trip_last_ts = now
    if dt <= 0:
        return

    rpm = data.get("Drehzahl", {}).get("value")
    inj = data.get("Einspritzzeit", {}).get("value")
    speed_kmh, speed_source = _get_speed_kmh(data)

    live_lph = None
    live_l100 = None
    if isinstance(rpm, (int, float)) and isinstance(inj, (int, float)):
        # Conservative estimate constant for mono-injector setup (documented as estimated).
        k = float(state.calibration["k_estimate"])
        live_lph = max(0.0, float(rpm) * float(inj) * k)
        if speed_kmh is not None and speed_kmh > 3:
            live_l100 = (live_lph / speed_kmh) * 100.0

    state.trip["live_lph"] = round(live_lph, 2) if live_lph is not None else None
    state.trip["live_l_per_100km"] = round(live_l100, 2) if live_l100 is not None else None
    state.trip["speed_kmh"] = round(speed_kmh, 1) if speed_kmh is not None else None
    state.trip["speed_source"] = speed_source

    if speed_kmh is not None and speed_kmh > 1:
        state.trip["distance_km"] += speed_kmh * (dt / 3600.0)
        state.trip["drive_time_s"] += dt
    if live_lph is not None and live_lph > 0:
        state.trip["fuel_l"] += live_lph * (dt / 3600.0)

    if state.trip["drive_time_s"] > 0:
        avg_speed = state.trip["distance_km"] / (state.trip["drive_time_s"] / 3600.0)
        state.trip["avg_speed_kmh"] = round(avg_speed, 1)
    if state.trip["distance_km"] > 0.1:
        state.trip["avg_l_per_100km"] = round((state.trip["fuel_l"] / state.trip["distance_km"]) * 100.0, 2)


def _reset_trip_state():
    state.trip = {
        "distance_km": 0.0,
        "fuel_l": 0.0,
        "drive_time_s": 0.0,
        "avg_speed_kmh": None,
        "avg_l_per_100km": None,
        "live_lph": None,
        "live_l_per_100km": None,
        "speed_kmh": None,
        "speed_source": "N/A",
    }
    state._trip_last_ts = time.time()


def _recalculate_trip_averages():
    drive_time_s = state.trip["drive_time_s"]
    distance_km = state.trip["distance_km"]
    fuel_l = state.trip["fuel_l"]
    state.trip["avg_speed_kmh"] = None
    state.trip["avg_l_per_100km"] = None
    if drive_time_s > 0 and distance_km > 0:
        avg_speed = distance_km / (drive_time_s / 3600.0)
        state.trip["avg_speed_kmh"] = round(avg_speed, 1)
    if distance_km > 0.1 and fuel_l > 0:
        state.trip["avg_l_per_100km"] = round((fuel_l / distance_km) * 100.0, 2)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _apply_soft_learning(observed_liters: float, source: str):
    estimated = float(state.trip["fuel_l"])
    distance = float(state.trip["distance_km"])
    if observed_liters <= 0 or estimated < 0.25 or distance < 3:
        state.calibration["status"] = "standard"
        return

    ratio = _clamp(observed_liters / estimated, 0.5, 1.5)
    current_k = float(state.calibration["k_estimate"])
    target_k = _clamp(current_k * ratio, 0.0004, 0.0030)
    alpha = 0.20 if source == "refuel" else 0.08
    new_k = current_k + alpha * (target_k - current_k)

    state.calibration["k_estimate"] = round(new_k, 7)
    state.calibration["learn_samples"] = int(state.calibration["learn_samples"]) + 1
    state.calibration["last_source"] = source
    state.calibration["last_observed_liters"] = round(observed_liters, 2)
    state.calibration["last_ratio"] = round(ratio, 3)
    state.calibration["status"] = "learning"


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


class GPSSpeedUpdate(BaseModel):
    speed_kmh: Optional[float] = None


class TripDistanceUpdate(BaseModel):
    distance_km: float


class RefuelUpdate(BaseModel):
    liters: float


class TankAdjustUpdate(BaseModel):
    delta_liters: float


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
        "trip":             state.trip,
        "calibration":      state.calibration,
    }


@app.post("/api/gps-speed")
async def api_gps_speed(update: GPSSpeedUpdate):
    state.gps_speed_kmh = update.speed_kmh if update.speed_kmh is not None else None
    state.gps_speed_ts = time.time()
    return {"ok": True}


@app.post("/api/trip/reset")
async def api_trip_reset():
    _reset_trip_state()
    await _broadcast()
    return {"ok": True, "trip": state.trip}


@app.post("/api/trip/distance")
async def api_trip_distance(update: TripDistanceUpdate):
    # Manual correction for a known driven distance (e.g., odometer value).
    state.trip["distance_km"] = max(0.0, float(update.distance_km))
    _recalculate_trip_averages()
    await _broadcast()
    return {"ok": True, "trip": state.trip}


@app.post("/api/fuel/refuel")
async def api_fuel_refuel(update: RefuelUpdate):
    liters = float(update.liters)
    if liters <= 0 or liters > 120:
        return {"ok": False, "error": "Liter außerhalb gültigem Bereich"}
    _apply_soft_learning(liters, "refuel")
    if state.calibration["tank_level_est_l"] is None:
        state.calibration["tank_level_est_l"] = 0.0
    state.calibration["tank_level_est_l"] = round(float(state.calibration["tank_level_est_l"]) + liters, 2)
    await _broadcast()
    return {"ok": True, "trip": state.trip, "calibration": state.calibration}


@app.post("/api/fuel/adjust")
async def api_fuel_adjust(update: TankAdjustUpdate):
    delta = float(update.delta_liters)
    if delta < -40 or delta > 40:
        return {"ok": False, "error": "Delta außerhalb gültigem Bereich"}
    if state.calibration["tank_level_est_l"] is None:
        state.calibration["tank_level_est_l"] = 0.0
    state.calibration["tank_level_est_l"] = round(
        max(0.0, float(state.calibration["tank_level_est_l"]) + delta), 2
    )
    observed = max(0.1, float(state.trip["fuel_l"]) - delta)
    _apply_soft_learning(observed, "adjust")
    await _broadcast()
    return {"ok": True, "trip": state.trip, "calibration": state.calibration}


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
