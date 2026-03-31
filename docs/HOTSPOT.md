# Hotspot Bridge (passatpi) - Auto (Fahrzeug) Betrieb

Dieses Runbook beschreibt die Schritte, um den Raspberry Pi Zero 2W (`passatpi`) als WLAN-Hotspot für das Dashboard zu betreiben.

## Ziel

- Der Raspi sendet ein WLAN `PassatECU`.
- Dein Handy/PC verbindet sich mit dem WLAN.
- Dashboard ist erreichbar unter `http://192.168.4.1:1994`.
- Der KKL/K-Line Adapter bleibt kabelgebunden am Raspi.

## Vorbedingungen (empfohlen)

- Dashboard/Server läuft bereits als `systemd` Service (`passat-ecu.service`) im Heimnetz.
- USB-Serial Device ist vorhanden, z.B. `/dev/ttyUSB0`.

## Moduswechsel (Auto vs. Heimnetz)

Nach der Einrichtung kannst du zwischen **Hotspot (Auto)** und **normalem WLAN-Client (Werkstatt/Updates)** umschalten:

```bash
cd ~/piB4ECU
sudo ./scripts/pib4ecu-net-mode.sh car    # Fahrzeug / Hotspot
sudo ./scripts/pib4ecu-net-mode.sh home  # Heim-WLAN (NetworkManager oder dhcpcd)
sudo ./scripts/pib4ecu-net-mode.sh auto  # OBD erkannt => car, sonst home
sudo ./scripts/pib4ecu-net-mode.sh lock  # Wartung erzwingt home
sudo ./scripts/pib4ecu-net-mode.sh unlock
sudo ./scripts/pib4ecu-net-mode.sh status
```

Details und USB-Werkstatt-Modus: `docs/USB_GADGET.md`. Nach dem Wechsel **Reboot** empfohlen.
Fuer automatisches Verhalten nach jedem Neustart die Boot-Unit aus `deploy/systemd/pib4ecu-net-mode-apply.service` aktivieren (siehe `docs/SETUP.md`).

## Hotspot einrichten (mit Auto-Interface-Erkennung)

### 1) WLAN-Interface ermitteln

```bash
sudo apt install -y iw
WIFI_IFACE="$(iw dev | awk '$1=="Interface"{print $2; exit}')"
echo "Hotspot uses interface: ${WIFI_IFACE}"
```

### 2) Pakete installieren

```bash
sudo apt install -y hostapd dnsmasq
```

### 3) `hostapd.conf` schreiben

```bash
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
```

### 4) DHCP via `dnsmasq` aktivieren

```bash
sudo tee -a /etc/dnsmasq.conf > /dev/null <<EOF
interface=${WIFI_IFACE}
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
EOF
```

### 5) Statische Hotspot-IP (Gateway) via systemd oneshot setzen

> Vorteil: funktioniert auch, wenn `dhcpcd` inaktiv ist.

```bash
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
```

### 6) Client-WLAN dauerhaft deaktivieren (damit Heimnetz nicht automatisch „greift“)

```bash
sudo systemctl disable --now NetworkManager 2>/dev/null || true
sudo systemctl disable --now "wpa_supplicant@${WIFI_IFACE}.service" 2>/dev/null || true
```

### 7) Dienste starten + reboot

```bash
sudo systemctl unmask hostapd
sudo systemctl enable hostapd dnsmasq
sudo reboot
```

## Verbindungstest im Auto

1. Handy verbindet sich mit `PassatECU`
2. Browser -> `http://192.168.4.1:1994`
3. In der `passat-ecu.service` Ausgabe sollten periodisch ECU-Requests / mögliche Timeouts auftauchen, bis die ECU wirklich verbunden ist.

## Recovery (wenn Hotspot nicht anspringt)

### Symptom: weder Heim-WLAN noch `PassatECU`-Hotspot

Das OLED zeigt `HOME / NO OBD` nur den **gewünschten Netz-Modus** (Datei `auto`/`home`) und den **OBD-Status** — nicht, ob WLAN wirklich verbunden ist.

1. Lokal am Pi (USB-Tastatur + Monitor, oder serielles Konsolenkabel), eingeloggt:

```bash
cd ~/piB4ECU
sudo ./scripts/pib4ecu-net-mode.sh status
```

- Steht dort **`effective_mode: usb`**, war der Werkstatt-Profil aktiv: für Heimnetz **`sudo ./scripts/pib4ecu-net-mode.sh home`** (oder **`auto`**) und **`sudo reboot`**.
- Steht **`effective_mode: home`**, aber WLAN tot: **`sudo ./scripts/pib4ecu-net-mode.sh home`** nochmal ausführen (stellt u.a. NetworkManager + WLAN wieder her), dann **`sudo reboot`**. Prüfen: **`rfkill list`**, **`ip link`**, **`nmcli dev status`**.

2. Hotspot erzwingen (wenn Heim-WLAN egal ist):

```bash
cd ~/piB4ECU
sudo ./scripts/pib4ecu-net-mode.sh car
sudo reboot
```

### Nur Hotspot springt nicht an, Heimnetz geht

```bash
cd ~/piB4ECU
sudo ./scripts/pib4ecu-net-mode.sh home
sudo reboot
```

Oder manuell:

```bash
sudo systemctl disable --now hostapd dnsmasq
sudo systemctl disable --now passatpi-hotspot-ip
sudo systemctl reboot
```

Wenn SSH weg ist: lokal am Raspi (Keyboard/Monitor) oder per SD-Karten-Edit wieder herholen.

