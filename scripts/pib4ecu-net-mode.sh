#!/usr/bin/env bash
# Switch Raspberry Pi Wi-Fi between car hotspot (hostapd) and home client (NetworkManager / dhcpcd).
# Supports persistent auto mode: OBD adapter present => car, else home.
set -u

MODE_DIR="/etc/pib4ecu"
MODE_FILE="${MODE_DIR}/net-mode"
LOCK_FILE="${MODE_DIR}/maintenance.lock"
OBD_BY_ID_GLOB="/dev/serial/by-id/*"
IW_BIN=""

usage() {
  echo "Usage: sudo $0 {car|home|usb|auto|apply|lock|unlock|status}" >&2
  echo "  car     force hotspot mode" >&2
  echo "  home    force home/client mode" >&2
  echo "  usb     force workshop USB profile (Wi-Fi stacks off)" >&2
  echo "  auto    persist auto mode (OBD present => car, else home)" >&2
  echo "  apply   apply effective mode now (used by boot service)" >&2
  echo "  lock    enable maintenance lock (forces home while present)" >&2
  echo "  unlock  remove maintenance lock" >&2
  echo "  status  show marker, lock, OBD state, effective mode and unit states" >&2
  exit 1
}

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "Run as root: sudo $0 $*" >&2
    exit 1
  fi
}

resolve_iw_bin() {
  if [[ -n "${IW_BIN}" ]]; then
    return
  fi
  for candidate in "$(command -v iw 2>/dev/null || true)" /sbin/iw /usr/sbin/iw /usr/bin/iw; do
    if [[ -n "${candidate}" && -x "${candidate}" ]]; then
      IW_BIN="${candidate}"
      return
    fi
  done
  echo "Missing 'iw'. Install: sudo apt install -y iw" >&2
  exit 1
}

wifi_iface() {
  resolve_iw_bin
  local iface
  iface="$("${IW_BIN}" dev 2>/dev/null | awk '$1 == "Interface" { print $2; exit }')"
  if [[ -z "${iface}" ]]; then
    echo "No wireless interface found (iw dev)." >&2
    exit 1
  fi
  echo "${iface}"
}

# Does not exit if wlan or iw is missing (e.g. recovery / minimal images).
wifi_iface_optional() {
  local candidate iface
  for candidate in "$(command -v iw 2>/dev/null || true)" /sbin/iw /usr/sbin/iw /usr/bin/iw; do
    if [[ -n "${candidate}" && -x "${candidate}" ]]; then
      iface="$("${candidate}" dev 2>/dev/null | awk '$1 == "Interface" { print $2; exit }')"
      echo "${iface}"
      return 0
    fi
  done
  echo ""
}

has_networkmanager() {
  systemctl cat NetworkManager.service >/dev/null 2>&1
}

write_mode() {
  mkdir -p "${MODE_DIR}"
  echo "$1" > "${MODE_FILE}"
  chmod 644 "${MODE_FILE}"
}

enable_lock() {
  mkdir -p "${MODE_DIR}"
  : > "${LOCK_FILE}"
  chmod 644 "${LOCK_FILE}"
}

disable_lock() {
  rm -f "${LOCK_FILE}"
}

is_lock_enabled() {
  [[ -f "${LOCK_FILE}" ]]
}

mode_from_file() {
  if [[ -f "${MODE_FILE}" ]]; then
    local mode
    mode="$(tr -d '[:space:]' < "${MODE_FILE}")"
    case "${mode}" in
      car|home|usb|auto) echo "${mode}" ;;
      *) echo "auto" ;;
    esac
  else
    echo "auto"
  fi
}

obd_present() {
  compgen -G "${OBD_BY_ID_GLOB}" >/dev/null 2>&1
}

effective_mode() {
  local selected
  selected="$(mode_from_file)"
  if is_lock_enabled; then
    echo "home"
    return
  fi
  case "${selected}" in
    car|home|usb)
      echo "${selected}"
      ;;
    auto)
      if obd_present; then
        echo "car"
      else
        echo "home"
      fi
      ;;
  esac
}

disable_hotspot_stack() {
  systemctl disable --now passatpi-hotspot-ip 2>/dev/null || true
  systemctl disable --now hostapd dnsmasq 2>/dev/null || true
  systemctl stop hostapd dnsmasq 2>/dev/null || true
}

apply_car() {
  local iface
  iface="$(wifi_iface)"
  disable_hotspot_stack
  systemctl disable --now NetworkManager 2>/dev/null || true
  systemctl disable --now "wpa_supplicant@${iface}.service" 2>/dev/null || true
  systemctl unmask hostapd 2>/dev/null || true
  systemctl enable hostapd dnsmasq 2>/dev/null || true
  systemctl enable passatpi-hotspot-ip 2>/dev/null || true
  systemctl start hostapd 2>/dev/null || true
  systemctl start dnsmasq 2>/dev/null || true
  systemctl start passatpi-hotspot-ip 2>/dev/null || true
}

apply_home() {
  disable_hotspot_stack
  systemctl unmask NetworkManager 2>/dev/null || true
  if has_networkmanager; then
    systemctl enable --now NetworkManager
    # After car/usb mode, wlan can stay down or "unmanaged" until explicitly nudged.
    if command -v nmcli >/dev/null 2>&1; then
      nmcli radio wifi on 2>/dev/null || true
      local iface
      iface="$(wifi_iface_optional)"
      if [[ -n "${iface}" ]]; then
        nmcli dev set "${iface}" managed yes 2>/dev/null || true
      fi
    fi
  else
    systemctl enable --now dhcpcd 2>/dev/null || true
    local iface
    iface="$(wifi_iface_optional)"
    if [[ -n "${iface}" ]]; then
      systemctl unmask "wpa_supplicant@${iface}.service" 2>/dev/null || true
      systemctl enable --now "wpa_supplicant@${iface}.service" 2>/dev/null || true
    fi
    echo "NetworkManager not installed; started dhcpcd. Configure Wi-Fi: sudo raspi-config"
  fi
}

apply_usb() {
  disable_hotspot_stack
  systemctl disable --now NetworkManager 2>/dev/null || true
  local iface
  resolve_iw_bin
  iface="$("${IW_BIN}" dev 2>/dev/null | awk '$1 == "Interface" { print $2; exit }' || true)"
  if [[ -n "${iface}" ]]; then
    systemctl disable --now "wpa_supplicant@${iface}.service" 2>/dev/null || true
  fi
}

cmd_status() {
  echo "net-mode file: ${MODE_FILE}"
  if [[ -f "${MODE_FILE}" ]]; then
    cat "${MODE_FILE}"
  else
    echo "(not set)"
  fi
  echo "maintenance_lock: $([[ -f "${LOCK_FILE}" ]] && echo on || echo off)"
  echo "obd_by_id_present: $(obd_present && echo yes || echo no)"
  echo "effective_mode: $(effective_mode)"
  echo ""
  for u in hostapd dnsmasq passatpi-hotspot-ip NetworkManager dhcpcd; do
    printf "%-22s enabled=%s active=%s\n" "${u}" \
      "$(systemctl is-enabled "${u}" 2>/dev/null || echo unknown)" \
      "$(systemctl is-active "${u}" 2>/dev/null || echo unknown)"
  done
  local iface
  resolve_iw_bin
  iface="$("${IW_BIN}" dev 2>/dev/null | awk '$1 == "Interface" { print $2; exit }' || true)"
  if [[ -n "${iface}" ]]; then
    echo ""
    echo "wpa_supplicant@${iface}: enabled=$(systemctl is-enabled "wpa_supplicant@${iface}" 2>/dev/null || echo unknown) active=$(systemctl is-active "wpa_supplicant@${iface}" 2>/dev/null || echo unknown)"
  fi
}

cmd_car() {
  require_root car
  disable_lock
  write_mode car
  apply_car
  echo "Mode: car (hotspot). If services failed, complete docs/HOTSPOT.md first."
  echo "Reboot recommended: sudo reboot"
}

cmd_home() {
  require_root home
  disable_lock
  write_mode home
  apply_home
  echo "Mode: home (client Wi-Fi). Reboot recommended: sudo reboot"
}

cmd_usb() {
  require_root usb
  disable_lock
  write_mode usb
  apply_usb
  echo "Mode: usb (workshop). Wi-Fi client stack disabled; follow docs/USB_GADGET.md for g_ether, then reboot."
}

cmd_auto() {
  require_root auto
  disable_lock
  write_mode auto
  cmd_apply
}

cmd_lock() {
  require_root lock
  enable_lock
  write_mode auto
  cmd_apply
  echo "Maintenance lock enabled. Effective mode forced to home."
}

cmd_unlock() {
  require_root unlock
  disable_lock
  echo "Maintenance lock disabled."
}

cmd_apply() {
  require_root apply
  local target
  target="$(effective_mode)"
  case "${target}" in
    car) apply_car ;;
    home) apply_home ;;
    usb) apply_usb ;;
    *) echo "Unexpected effective mode: ${target}" >&2; exit 1 ;;
  esac
  echo "Applied mode: ${target}"
}

main() {
  case "${1:-}" in
    status) cmd_status ;;
    car) cmd_car ;;
    home) cmd_home ;;
    usb) cmd_usb ;;
    auto) cmd_auto ;;
    apply) cmd_apply ;;
    lock) cmd_lock ;;
    unlock) cmd_unlock ;;
    *) usage ;;
  esac
}

main "$@"
