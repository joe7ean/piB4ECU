# piB4ECU

Live-Dashboard fuer VW Passat B4 ECU-Daten (KW1281/K-Line) auf Raspberry Pi.

## Projektstruktur

- `app/` - Laufzeitcode (FastAPI-Server, KW1281-Treiber, Dashboard, CLI-Trace)
- `docs/` - Setup- und Betriebsdokumentation
- `requirements.txt` - Python-Abhaengigkeiten

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app/server.py
```

Danach im Browser:

- `http://localhost:8000` (lokal)
- `http://<raspi-ip>:8000` (im Netzwerk)

## Wichtige Dateien

- `app/server.py` - FastAPI + WebSocket Streaming + API
- `app/kw1281.py` - KW1281 Protokoll und Decoder
- `app/dashboard.html` - Smartphone-optimiertes Dashboard
- `app/ecu_trace.py` - CLI fuer Handshake/Diagnose

## Doku

- `docs/SETUP.md` - Raspberry-Pi Setup inkl. systemd Service
- `docs/HOTSPOT.md` - Hotspot-Betrieb im Auto
- `docs/MEASURING_BLOCKS.md` - Dokumentierte Messwertbloecke

## Hinweise fuer Veroeffentlichung

- Laufzeit- und lokale Dateien sind per `.gitignore` ausgeschlossen (`.venv`, `__pycache__`, `.cursor`).
- Optionale Ideen/Notizen bleiben in `ideas.md` lokal und untracked.
