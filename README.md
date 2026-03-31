# piB4ECU

Live-Dashboard für VW Passat B4 und andere VW/Audi/Seat/Skoda-Modelle aus den 90ern mit KW1281/K-Line-ECU (z.B. Golf 3, Audi 80/100, Seat Toledo, Skoda Felicia) auf Raspberry Pi.

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

- `http://localhost:1994` (lokal)
- `http://<raspi-ip>:1994` (im Netzwerk)

Optional anderer Port:

- setze `ECU_HTTP_PORT=<port>`
- fuer Port `80` bei systemd fuer User `pi` zusaetzlich `AmbientCapabilities=CAP_NET_BIND_SERVICE`

## Telemetry Logging (Engine, F1-Style)

Der Server loggt standardmaessig Engine-Telemetrie im Hintergrund (optimiert fuer Pi Zero 2W).

- Format: rotierende JSONL-Dateien (`engine-telemetry-*.jsonl.gz`)
- Basisordner: `./logs`
- Logging ist vom Dashboard entkoppelt (Queue + async Writer), damit UI/Streaming priorisiert bleibt

Wichtige ENV-Variablen:

- `ECU_LOG_ENABLED=1` (an/aus)
- `ECU_LOG_DIR=./logs` (Zielordner)
- `ECU_LOG_ROTATE_MB=25` (Rotation pro Datei)
- `ECU_LOG_MAX_FILES=12` (max. Archivdateien)
- `ECU_LOG_MAX_TOTAL_MB=300` (max. Gesamtgroesse der Archive)
- `ECU_LOG_MAX_QUEUE=2000` (Puffer, danach kontrolliertes Dropping)
- `ECU_LOG_GZIP=1` (rotierte Dateien komprimieren)

Beispiele:

```bash
# Standard-Logging aktiv (Default)
python app/server.py

# Logging komplett aus
ECU_LOG_ENABLED=0 python app/server.py

# Eigener Speicherpfad und konservativeres Retention-Limit
ECU_LOG_DIR=/var/log/piB4ECU ECU_LOG_ROTATE_MB=10 ECU_LOG_MAX_FILES=8 python app/server.py
```

## Telemetry Analysis (Graphs)

Interaktive Auswertung der Telemetrie-Logs ist mit `tools/telemetry_viewer.py` moeglich.
Fuer eine nutzerfreundliche Browser-Oberflaeche gibt es zusaetzlich `tools/telemetry_app.py` (Streamlit).

Analyse-Abhaengigkeiten installieren:

```bash
pip install -r requirements-analysis.txt
```

Metriken anzeigen:

```bash
python tools/telemetry_viewer.py --log-dir logs list-metrics
```

Nutzerfreundliche UI starten:

```bash
streamlit run tools/telemetry_app.py
```

Dann im Browser die angezeigte lokale URL oeffnen (typisch `http://localhost:8501`).
Die UI nutzt als Standard-Logpfad `ECU_LOG_DIR` (falls gesetzt), sonst automatisch `<repo-root>/logs`.

Eine Metrik ueber Zeit vergleichen (alle Runs):

```bash
python tools/telemetry_viewer.py --log-dir logs plot-metric --metric "Drehzahl" --out analysis/out/rpm.html
```

Zwei Metriken als Scatter vergleichen:

```bash
python tools/telemetry_viewer.py --log-dir logs plot-pair --x "Drehzahl" --y "Einspritzzeit" --out analysis/out/inj_vs_rpm.html
```

Nur bestimmte Runs/Fahrten auswerten:

```bash
python tools/telemetry_viewer.py --log-dir logs --run-filter "20260327" plot-metric --metric "Kühlmitteltemperatur" --out analysis/out/coolant_20260327.html
```

## Wichtige Dateien

- `app/server.py` - FastAPI + WebSocket Streaming + API
- `app/kw1281.py` - KW1281 Protokoll und Decoder
- `app/dashboard.html` - Smartphone-optimiertes Dashboard
- `app/ecu_trace.py` - CLI fuer Handshake/Diagnose

## Doku

- `docs/SETUP.md` - Raspberry-Pi Setup inkl. systemd Service
- `docs/OLED.md` - OLED Mini-Display Setup (Software, Service, Layout)
- `docs/OLED_HARDWARE.md` - OLED Verdrahtung (Pi Pins, I2C, Spannung)
- OLED: on the Pi, `python tools/oled_status.py --test-live` (or `--test-screen …`) holds one fake screen; `--test` cycles all — see `docs/OLED.md`
- `docs/HOTSPOT.md` - Hotspot-Betrieb im Auto
- `docs/USB_GADGET.md` - USB-Ethernet-Gadget (Werkstatt ohne WLAN)
- `scripts/pib4ecu-net-mode.sh` - Umschalten car / home / usb / auto + lock/unlock (siehe `docs/SETUP.md`)
- `deploy/systemd/pib4ecu-net-mode-apply.service` - Boot-Policy: OBD erkannt => car, sonst home
- `docs/MEASURING_BLOCKS.md` - Dokumentierte Messwertbloecke
- `CHANGELOG.md` - Aenderungshistorie und Releases

## OTA Updates (Tag-basiert)

Fuer Updates direkt im Auto sind zwei Skripte enthalten:

- `scripts/update.sh` - deployt `origin/main` oder ein explizites Release-Tag
- `scripts/rollback.sh` - springt auf die zuletzt installierte Version zurueck

Beispiele:

```bash
./scripts/update.sh
./scripts/update.sh v1.0.0-alpha.1
./scripts/update.sh --set-time "2026-03-26 14:35:00"
CALLER_UTC="$(date -u '+%Y-%m-%d %H:%M:%S')" ./scripts/update.sh --set-time-from-ssh
./scripts/rollback.sh
```

Die Skripte verwalten den Deploy-Status in `.deploy-state` (`CURRENT_REF`, `PREVIOUS_REF`, Commits).
Bei stark falscher Systemzeit versucht `update.sh` automatisch einen Best-Effort Sync (falls Internet verfuegbar ist), oder nimmt explizit `--set-time`.

## Release Status

Aktueller Release-Kanal: `v1.0.0-alpha.1` (Pre-Release)

## Hinweise fuer Veroeffentlichung

- Laufzeit- und lokale Dateien sind per `.gitignore` ausgeschlossen (`.venv`, `__pycache__`, `.cursor`).

- Lizenz: `MIT` (siehe `LICENSE`)
