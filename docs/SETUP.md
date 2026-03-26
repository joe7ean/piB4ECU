# Passat B4 ECU Dashboard - Setup (Raspberry Pi Zero 2W)

Diese Anleitung richtet das Projekt auf einem Raspberry Pi mit Standard-Port `80` ein.

## Voraussetzungen

- Raspberry Pi OS Lite (Bookworm, 64-bit)
- SSH/WLAN konfiguriert
- KKL-Adapter angeschlossen (typisch `/dev/ttyUSB0`)

## 1) System vorbereiten

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv
```

## 2) Projekt installieren

```bash
git clone https://github.com/joe7ean/piB4ECU.git
cd ~/piB4ECU

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3) Serial-Rechte setzen

```bash
sudo usermod -a -G dialout $USER
```

Danach einmal ab- und wieder anmelden (oder reboot), damit die Gruppe aktiv ist.

Port prüfen:

```bash
ls /dev/ttyUSB*
```

## 4) Lokal testen (ohne systemd)

```bash
source .venv/bin/activate
python app/server.py
```

Aufruf:

- `http://localhost`
- `http://<raspi-ip>`

## 5) Vor Hotspot: ECU-Verbindung gezielt mit `ecu_trace.py` pruefen

Empfohlene Reihenfolge fuer ein stabiles Setup:

1. Erst mit Rechner/Raspi direkt per OBD/KKL-Kabel testen
2. Dann Webserver lokal pruefen
3. Erst danach Hotspot und Autobetrieb aktivieren

So trennst du Kommunikationsprobleme (K-Line/ECU) sauber von Netzwerk-/Hotspot-Themen.

```bash
source .venv/bin/activate
python app/ecu_trace.py --port /dev/ttyUSB0 --baud 4800 --attempts 10
python app/ecu_trace.py --measure 1 --attempts 3
```

Hinweis fuer andere Motor-/Steuergeraetevarianten:

- `ecu_trace.py` ist ideal, um Handshake und Messwertblock-Lesen isoliert zu validieren.
- Wenn dein Steuergeraet nicht auf Standardwerte reagiert, zuerst hier debuggen (Port, Baud, Timing, Versuche).
- Fuer abweichende ECU-Adressen/Blockinhalte kannst du danach gezielt `app/kw1281.py` bzw. die Adresse in `app/ecu_trace.py` anpassen.

## 6) Autostart mit systemd (Port 80)

Service-Datei erstellen:

```bash
sudo tee /etc/systemd/system/passat-ecu.service > /dev/null << 'EOF'
[Unit]
Description=Passat B4 ECU Dashboard
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/piB4ECU
Environment=ECU_HTTP_PORT=80
AmbientCapabilities=CAP_NET_BIND_SERVICE
ExecStart=/home/pi/piB4ECU/.venv/bin/python app/server.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
```

Aktivieren und starten:

```bash
sudo systemctl daemon-reload
sudo systemctl enable passat-ecu
sudo systemctl start passat-ecu
```

Status/Logs:

```bash
sudo systemctl status passat-ecu
journalctl -u passat-ecu -f
```

## 7) Zugriff vom Handy

- Im selben Netzwerk: `http://<raspi-ip>`
- Optional als PWA speichern: Safari -> Teilen -> "Zum Home-Bildschirm"

## 8) Hotspot-Betrieb im Auto

Die Hotspot-Einrichtung ist in `docs/HOTSPOT.md` beschrieben.

## Troubleshooting

- `Permission denied` auf `/dev/ttyUSB0`: Benutzer noch nicht in `dialout` aktiv
- ECU antwortet nicht: Zündung/5-Baud-Init prüfen, ggf. erneut versuchen
- Kein `/dev/ttyUSB0`: Adapter/Kabel/Chip-Treiber prüfen
