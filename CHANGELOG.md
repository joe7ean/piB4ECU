# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Added
- `scripts/pib4ecu-net-mode.sh` to switch between car (hotspot), home (client Wi-Fi), and usb (workshop) network profiles.
- `docs/USB_GADGET.md` for USB Ethernet gadget setup on Pi Zero 2W.
- `deploy/systemd/pib4ecu-net-mode-apply.service` for boot-time network mode apply.

### Changed
- Default HTTP port is now `1994` (still overridable via `ECU_HTTP_PORT`, e.g. `80` for reverse-proxy setups).
- Network mode script now supports `auto` (OBD by-id => car, else home), `apply`, and `lock`/`unlock` maintenance flow.
- `pib4ecu-net-mode-apply.service` runs after `network.target` (avoids breaking client Wi-Fi at boot). `apply_home` nudges NetworkManager / `wpa_supplicant` so wlan is not left disabled after car/usb.
- OLED status script (`tools/oled_status.py`) uses system TrueType (DejaVu Bold by default) with auto-sized lines for 128×32; compact live labels (`/100`, `Lh`). Env: `ECU_OLED_FONT`, `ECU_OLED_TTF_MAX` / `ECU_OLED_TTF_MIN`, margins/gap — see `docs/OLED.md`.
- OLED `--test` mode: longer default base dwell (`ECU_OLED_TEST_STEP_S` default 4s), per-phase multipliers, mandatory blank pause before cycle (`ECU_OLED_TEST_BLANK_BEFORE_S`, `--test-blank-s`), and blank on exit; optional `ECU_OLED_TEST_PHASE_MULT` / `ECU_OLED_TEST_DWELL_MIN_S`.
- OLED single-screen test fixtures: `--test-screen NAME` and shorthand `--test-live`, `--test-home-no-obd`, etc. (holds until Ctrl+C); overrides `ECU_OLED_TEST_CYCLE` when used.
- OLED test rendering ignores host `/etc/pib4ecu/net-mode` (fixture `net_mode` only); live two-row view vertically centers the text block on 128×32.
- OLED: exclusive lock file so only one `oled_status.py` uses I2C (avoids flicker if service + manual test); `ECU_OLED_PAD_Y` + stricter height / `textbbox` checks to reduce bottom clipping; env `ECU_OLED_LOCK_*`, `ECU_OLED_PAD_Y`.

## [1.0.0-alpha.1] - 2026-03-26

### Added
- Root `README.md` with quick start and runtime notes.
- `docs/SETUP.md` and `docs/MEASURING_BLOCKS.md` as consolidated project docs.
- `app/ecu_trace.py` documentation for ECU-first diagnostic workflow.
- `LICENSE` (MIT).

### Changed
- Reorganized project structure into `app/` and `docs/`.
- Default HTTP port switched to `80` (overridable via `ECU_HTTP_PORT`).
- Setup documentation rewritten for clearer Raspberry Pi deployment steps.

### Removed
- Tracked local artifacts (virtualenv, caches, local editor state, old logs).
- Legacy folder layout under `passat_ecu--claudeOnline/`.
