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
#
# Ziel: Der Raspi (passatpi) sendet sein eigenes WLAN, während dein KKL/K-Line Adapter
# am Raspi über USB/Serial hängt. Das Dashboard ist dann im Auto unter
# `http://192.168.4.1:8000` erreichbar.
#
# Wichtiger Hinweis:
# - Nach Aktivierung des Hotspots kann die Heimnetz-SSH-Verbindung brechen.
#   Das ist erwartbar.
# - Wenn du dich ausgesperrt fühlst: Recovery unten nutzen.

# 6.1 WLAN-Interface automatisch bestimmen (statt hardcoded wlan0)
sudo apt install -y iw >/dev/null
WIFI_IFACE="$(iw dev | awk '$1=="Interface"{print $2; exit}')"
echo "Hotspot uses interface: ${WIFI_IFACE}"

# 6.2 Pakete installieren
sudo apt install -y hostapd dnsmasq

# 6.3 hostapd konfigurieren
sudo tee /etc/hostapd/hostapd.conf > /dev/null <<EOF
interface=${WIFI_IFACE}
ssid=PassatECU
hw_mode=g
channel=6
wpa=2
wpa_passphrase=passat1994
wpa_key_mgmt=WPA-PSK
wpa_pairwise=CCMP
EOF

# 6.4 dnsmasq konfigurieren (DHCP für Clients im Auto)
sudo tee -a /etc/dnsmasq.conf > /dev/null <<EOF
interface=${WIFI_IFACE}
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
EOF

# 6.5 Statische Hotspot-IP (Gateway) per systemd oneshot setzen
# Hintergrund: In deinem Setup ist `dhcpcd` inaktiv, deshalb verwenden wir nicht /etc/dhcpcd.conf.
sudo tee /etc/systemd/system/passatpi-hotspot-ip.service > /dev/null <<EOF
[Unit]
Description=Set static IP for PassatECU hotspot (${WIFI_IFACE})
After=hostapd.service
Wants=hostapd.service

[Service]
Type=oneshot
ExecStart=/sbin/ip addr replace 192.168.4.1/24 dev ${WIFI_IFACE}
ExecStartPost=/bin/systemctl restart dnsmasq
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable passatpi-hotspot-ip

# 6.6 Client-WLAN dauerhaft deaktivieren (damit Heimnetz nicht automatisch „greift“)
sudo systemctl disable --now NetworkManager 2>/dev/null || true
sudo systemctl disable --now "wpa_supplicant@${WIFI_IFACE}.service" 2>/dev/null || true

# 6.7 Dienste aktivieren + reboot
sudo systemctl unmask hostapd
sudo systemctl enable hostapd dnsmasq
sudo reboot

# Nach Reboot:
# - iPhone/Handy verbindet sich mit WLAN "PassatECU"
# - Dashboard: http://192.168.4.1:8000

# Recovery (falls Hotspot nicht geht):
# - SSH notfalls über lokalen Zugriff/SD-Card/Keyboard herstellen
# - Dann:
#   sudo systemctl disable --now hostapd dnsmasq
#   sudo systemctl reboot

# ── 7. Als PWA zum iPhone-Homescreen hinzufügen ───────────────────────────────
# Safari → Teilen-Button → "Zum Home-Bildschirm"
# → App startet im Vollbild, kein Browser-Chrome, fühlt sich nativ an

# ── V2 Dashboard Features (Aktuell) ───────────────────────────────────────────
# Das Dashboard wurde in Version 2 komplett überarbeitet:
# - Smartphone-First: Optimiert für die Anzeige auf dem Handy (Safari/Chrome).
# - Tabs: Aufteilung in `Antrieb`, `Trip` und `Fehler`.
# - Smart Feedback: Ein intelligentes Banner ganz oben analysiert die Live-Daten 
#   und gibt Tipps (z.B. "Motor kalt", "Schubabschaltung aktiv", "Falschluft-Warnung").
# - Bitmasken-Anzeige: Der Betriebszustand (Leerlauf, Lambdaregelung) wird live visualisiert.
# - Manueller Fehlerspeicher: Um das Live-Polling nicht zu stören (verhindert Ruckler), 
#   wird der Fehlerspeicher nur noch auf Knopfdruck ("Auslesen") im Fehler-Tab geladen.
# - GPS/Speed-Quelle: Auf der Antriebsseite wird GPS-km/h angezeigt; die Quelle (ECU/GPS/N/A)
#   ist transparent sichtbar.
# - Trip-Rechner (geschätzt): Der Trip-Tab zeigt Live-Verbrauch und Durchschnittswerte.
#   Alle Verbrauchswerte sind modellbasiert geschätzt (keine geeichte Werksmessung).
# - Theme-Toggle: Umschalter oben rechts (Tag/Nacht), Zustand bleibt im Browser gespeichert.
# - Trip-KM Korrektur: Im Trip-Tab kann die gefahrene Strecke manuell gesetzt werden
#   (z. B. per Tageskilometerzähler), dadurch wird vor allem `Ø L/100` realistischer.

# ── Troubleshooting ───────────────────────────────────────────────────────────
# "Permission denied" auf /dev/ttyUSB0 → Gruppe dialout fehlt (s. Schritt 3)
# ECU antwortet nicht → 5-Baud-Init braucht manchmal 2 Versuche (Zündung AUS/EIN)
# Kein /dev/ttyUSB0 → anderes Kabel, oder CP2102-Chip-Treiber fehlt
