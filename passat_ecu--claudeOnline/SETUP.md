# ══════════════════════════════════════════════════════════════════════════════
# Passat B4 ECU Dashboard — Setup für Raspberry Pi Zero 2W
# ══════════════════════════════════════════════════════════════════════════════

# ── 1. Raspi vorbereiten ───────────────────────────────────────────────────────

# Raspberry Pi OS Lite installieren (64-bit, Bookworm)
# SSH aktivieren, WLAN konfigurieren — via raspi-config oder direkt in /boot

# ── 2. Abhängigkeiten installieren ────────────────────────────────────────────

sudo apt update && sudo apt install -y python3-pip python3-venv

# Projekt kopieren (von deinem Mac per scp, oder direkt auf dem Pi klonen)
mkdir ~/passat_ecu && cd ~/passat_ecu

# Virtualenv anlegen
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

# ── 3. USB-Serial Rechte ──────────────────────────────────────────────────────

sudo usermod -a -G dialout $USER
# danach einmal ausloggen/einloggen, damit die Gruppe greift

# Port prüfen (KKL Adapter einstecken, dann):
ls /dev/ttyUSB*   # sollte /dev/ttyUSB0 zeigen

# ── 4. Demo-Modus testen (ohne KKL-Adapter) ───────────────────────────────────

# In server.py: DEMO_MODE = True setzen
python server.py
# Browser: http://localhost:8000

# ── 5. Autostart via systemd ──────────────────────────────────────────────────

# Service-Datei anlegen:
sudo tee /etc/systemd/system/passat-ecu.service > /dev/null << 'EOF'
[Unit]
Description=Passat B4 ECU Dashboard
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/passat_ecu
ExecStart=/home/pi/passat_ecu/.venv/bin/python server.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable passat-ecu
sudo systemctl start passat-ecu

# Status prüfen:
sudo systemctl status passat-ecu
journalctl -u passat-ecu -f   # Live-Log

# ── 6. iPhone verbinden ───────────────────────────────────────────────────────

# Option A — Heimnetz (Raspi + iPhone im selben WLAN)
# IP des Raspi herausfinden:
hostname -I
# Safari auf iPhone: http://192.168.x.x:8000
# → Als "Zum Home-Bildschirm" speichern → verhält sich wie eine native App!

# Option B — Raspi als Hotspot (kein Router nötig, ideal im Auto)
sudo apt install -y hostapd dnsmasq

sudo tee /etc/hostapd/hostapd.conf > /dev/null << 'EOF'
interface=wlan0
ssid=PassatECU
hw_mode=g
channel=6
wpa=2
wpa_passphrase=passat1994
wpa_key_mgmt=WPA-PSK
wpa_pairwise=CCMP
EOF

# dnsmasq konfigurieren für DHCP:
sudo tee -a /etc/dnsmasq.conf > /dev/null << 'EOF'
interface=wlan0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
EOF

# Statische IP für wlan0:
sudo tee -a /etc/dhcpcd.conf > /dev/null << 'EOF'
interface wlan0
static ip_address=192.168.4.1/24
nohook wpa_supplicant
EOF

sudo systemctl unmask hostapd
sudo systemctl enable hostapd dnsmasq
sudo reboot

# Nach Reboot: iPhone verbindet sich mit WLAN "PassatECU"
# Dashboard: http://192.168.4.1:8000

# ── 7. Als PWA zum iPhone-Homescreen hinzufügen ───────────────────────────────
# Safari → Teilen-Button → "Zum Home-Bildschirm"
# → App startet im Vollbild, kein Browser-Chrome, fühlt sich nativ an

# ── Troubleshooting ───────────────────────────────────────────────────────────
# "Permission denied" auf /dev/ttyUSB0 → Gruppe dialout fehlt (s. Schritt 3)
# ECU antwortet nicht → 5-Baud-Init braucht manchmal 2 Versuche (Zündung AUS/EIN)
# Kein /dev/ttyUSB0 → anderes Kabel, oder CP2102-Chip-Treiber fehlt
