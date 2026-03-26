# Milestone V1 — Passat B4 ECU Dashboard Bridge

Ziel von V1 ist: **im Auto** stabil ein Smartphone-Dashboard bekommen, ohne Heimnetz-Automatik, und ohne dass der Raspi nach Reboot die Hotspot-IP verliert.

## Änderungen / Features in V1

### Hotspot (Auto) stabil
- Hotspot-Konfiguration wurde in `SETUP.md` und `HOTSPOT.md` so ergänzt, dass die **statische Gateway-IP `192.168.4.1/24`** via `systemd`-oneshot gesetzt wird (statt `dhcpcd`), damit **nach Reboot immer IPv4 vorhanden ist**.
- Zusätzlich wird (im Hotspot-Setup) `NetworkManager` sowie `wpa_supplicant@<iface>` deaktiviert, damit der Raspi **nicht mehr automatisch ins Heimnetz** verbindet.

### Serial/KKL Adapter robust
- `server.py` nutzt den stabilen udev-Link:
  - `/dev/serial/by-id/usb-FTDI_USB__-__Serial_Cable_12345678-if00-port0`
  statt `/dev/ttyUSB0`, damit Hotplug/Reboot weniger oft zu einem “Adapter nicht gefunden” führen.

## Stand
- V1 ist ausreichend, um live Werte als WebSocket JSON an das Dashboard zu liefern.
- Version 2 (Dashboard-Overhaul) folgt mit Fokus auf deterministische Smartphone-UX und optional manuelles Fehlerspeicher-Auslesen.

