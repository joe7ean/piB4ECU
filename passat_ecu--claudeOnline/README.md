# Passat B4 ECU Dashboard (KW1281 / K-Line) - Raspi Bridge

Dieses Projekt verbindet einen `KKL/K-Line` Adapter (USB-Serial) mit einem Raspberry Pi Zero 2W (`passatpi`).
Auf dem Raspi läuft ein Webserver, der live ECU-Messwerte per WebSocket an ein mobiles Dashboard streamt.

## Überblick

- `kw1281.py`: KW1281/KWP-1281 Protokoll (K-Line) + Decoder
- `server.py`: FastAPI Server mit WebSocket Push (Livewerte + Fehlercodes)
- `dashboard.html`: PWA/Dashboard (Safari/iPhone-freundlich)
- `SETUP.md`: Schritt-für-Schritt Setup (inkl. Hotspot im Auto)

## Voraussetzung

- Raspberry Pi OS Lite 64-bit (Bookworm)
- USB-Serial KKL Adapter
- Ein 1994er Passat B4 (K-Line Diagnosepfad)

## Quick Start (Raspi im Heimnetz)

1. Raspi vorbereiten (SSH aktiv, WLAN verbunden)
2. Projekt auf Raspi legen nach:
   - `/home/pi/passat_ecu/`
3. In `~/passat_ecu`:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -r requirements.txt`
4. `passat-ecu.service` nutzen (siehe `SETUP.md`)
5. Im Browser öffnen:
   - `http://<raspi-ip>:8000`

## Im Auto: Hotspot-Modus

Siehe `SETUP.md`, Abschnitt "Option B — Raspi als Hotspot".
Werte sind danach erreichbar unter:

- `http://192.168.4.1:8000`

## Wichtige Hinweise

- Der Webserver erwartet `dashboard.html` im selben Verzeichnis wie `server.py` (WorkingDirectory in systemd ist dafür wichtig).
- Wenn das ECU nicht erreichbar ist, kommen im Log Timeouts: das ist normal solange kein ECU am Adapter hängt bzw. Zündung/Init nicht stimmt.
- Hotspot-Gateway-IP (`192.168.4.1/24`) wird per systemd oneshot gesetzt (damit es auch ohne `dhcpcd` nach Reboot zuverlässig funktioniert).

