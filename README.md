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

- `http://localhost` (lokal)
- `http://<raspi-ip>` (im Netzwerk)

Optional anderer Port:

- setze `ECU_HTTP_PORT=<port>`
- bei systemd fuer User `pi` zusaetzlich `AmbientCapabilities=CAP_NET_BIND_SERVICE`

## Wichtige Dateien

- `app/server.py` - FastAPI + WebSocket Streaming + API
- `app/kw1281.py` - KW1281 Protokoll und Decoder
- `app/dashboard.html` - Smartphone-optimiertes Dashboard
- `app/ecu_trace.py` - CLI fuer Handshake/Diagnose

## Doku

- `docs/SETUP.md` - Raspberry-Pi Setup inkl. systemd Service
- `docs/HOTSPOT.md` - Hotspot-Betrieb im Auto
- `docs/MEASURING_BLOCKS.md` - Dokumentierte Messwertbloecke
- `CHANGELOG.md` - Aenderungshistorie und Releases

## Release Status

Aktueller Release-Kanal: `v1.0.0-alpha.1` (Pre-Release)

## Hinweise fuer Veroeffentlichung

- Laufzeit- und lokale Dateien sind per `.gitignore` ausgeschlossen (`.venv`, `__pycache__`, `.cursor`).
- Optionale Ideen/Notizen bleiben in `ideas.md` lokal und untracked.
- Lizenz: `MIT` (siehe `LICENSE`)
