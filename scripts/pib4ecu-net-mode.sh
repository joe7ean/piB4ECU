#!/usr/bin/env bash
# Switch Raspberry Pi Wi-Fi between car hotspot (hostapd) and home client (NetworkManager / dhcpcd).
# Requires: iw (sudo apt install -y iw). See docs/HOTSPOT.md for initial hotspot setup.
set -u

MODE_DIR="/etc/pib4ecu"
MODE_FILE="${MODE_DIR}/net-mode"
HOTSPOT_UNITS=(hostapd dnsmasq passatpi-hotspot-ip)

usage() {
  echo "Usage: sudo $0 {car|home|usb|status}" >&2
  echo "  car   — AP mode (PassatECU hotspot), disable client Wi-Fi stack" >&2
  echo "  home  — disable hotspot; use NetworkManager if present, else dhcpcd" >&2
  echo "  usb   — disable hotspot + NetworkManager; use with USB gadget (see docs/USB_GADGET.md)" >&2
  echo "  status — show marker file and unit states" >&2
  exit 1
}

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "Run as root: sudo $0 $*" >&2
    exit 1
  fi
}

wifi_iface() {
  if ! command -v iw >/dev/null 2>&1; then
    echo "Missing 'iw'. Install: sudo apt install -y iw" >&2
    exit 1
  fi
  local iface
  iface="$(iw dev 2>/dev/null | awk '$1 == "Interface" { print $2; exit }')"
  if [[ -z "${iface}" ]]; then
    echo "No wireless interface found (iw dev)." >&2
    exit 1
  fi
  echo "${iface}"
}

has_networkmanager() {
  systemctl cat NetworkManager.service >/dev/null 2>&1
}

write_mode() {
  mkdir -p "${MODE_DIR}"
  echo "$1" > "${MODE_FILE}"
  chmod 644 "${MODE_FILE}"
}

stop_hotspot_stack() {
  systemctl disable --now passatpi-hotspot-ip 2>/dev/null || true
  systemctl disable --now hostapd dnsmasq 2>/dev/null || true
  systemctl stop hostapd dnsmasq 2>/dev/null || true
}

cmd_status() {
  echo "net-mode file: ${MODE_FILE}"
  if [[ -f "${MODE_FILE}" ]]; then
    cat "${MODE_FILE}"
  else
    echo "(not set)"
  fi
  echo ""
  for u in hostapd dnsmasq passatpi-hotspot-ip NetworkManager dhcpcd; do
    printf "%-22s enabled=%s active=%s\n" "${u}" \
      "$(systemctl is-enabled "${u}" 2>/dev/null || echo unknown)" \
      "$(systemctl is-active "${u}" 2>/dev/null || echo unknown)"
  done
  local iface
  iface="$(iw dev 2>/dev/null | awk '$1 == "Interface" { print $2; exit }' || true)"
  if [[ -n "${iface}" ]]; then
    echo ""
    echo "wpa_supplicant@${iface}: enabled=$(systemctl is-enabled "wpa_supplicant@${iface}" 2>/dev/null || echo unknown) active=$(systemctl is-active "wpa_supplicant@${iface}" 2>/dev/null || echo unknown)"
  fi
}

cmd_car() {
  require_root car
  local iface
  iface="$(wifi_iface)"
  stop_hotspot_stack
  systemctl disable --now NetworkManager 2>/dev/null || true
  systemctl disable --now "wpa_supplicant@${iface}.service" 2>/dev/null || true
  write_mode car
  systemctl unmask hostapd 2>/dev/null || true
  systemctl enable hostapd dnsmasq 2>/dev/null || true
  systemctl enable passatpi-hotspot-ip 2>/dev/null || true
  systemctl start hostapd 2>/dev/null || true
  systemctl start dnsmasq 2>/dev/null || true
  systemctl start passatpi-hotspot-ip 2>/dev/null || true
  echo "Mode: car (hotspot). If services failed, complete docs/HOTSPOT.md first."
  echo "Reboot recommended: sudo reboot"
}

cmd_home() {
  require_root home
  local iface
  iface="$(wifi_iface)"
  stop_hotspot_stack
  systemctl unmask NetworkManager 2>/dev/null || true
  if has_networkmanager; then
    systemctl enable --now NetworkManager
  else
    systemctl enable --now dhcpcd 2>/dev/null || true
    echo "NetworkManager not installed; started dhcpcd. Configure Wi-Fi: sudo raspi-config"
  fi
  write_mode home
  echo "Mode: home (client Wi-Fi). Reboot recommended: sudo reboot"
}

cmd_usb() {
  require_root usb
  stop_hotspot_stack
  systemctl disable --now NetworkManager 2>/dev/null || true
  local iface
  iface="$(iw dev 2>/dev/null | awk '$1 == "Interface" { print $2; exit }' || true)"
  if [[ -n "${iface}" ]]; then
    systemctl disable --now "wpa_supplicant@${iface}.service" 2>/dev/null || true
  fi
  write_mode usb
  echo "Mode: usb (workshop). Wi-Fi client stack disabled; follow docs/USB_GADGET.md for g_ether, then reboot."
}

main() {
  case "${1:-}" in
    status) cmd_status ;;
    car) cmd_car ;;
    home) cmd_home ;;
    usb) cmd_usb ;;
    *) usage ;;
  esac
}

main "$@"
