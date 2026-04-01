# OLED Mini Display (SSD1306 128x32)

This guide covers software setup and runtime behavior for the OLED status screen.
Hardware wiring lives in `docs/OLED_HARDWARE.md`.

## What it shows

Display priority is intentionally simple for a tiny 128x32 screen:

1. Error first (`engine_error`)
2. If not connected: `ECU CONNECT`
3. If connected and no error:
   - top row distributed: coolant (left) and voltage (right)
   - second row: compact live consumption (`7.1/100` style; secondary `Lh` or `kmh` on the same line when width allows)

Boot/wait states are centered text (`BOOTING`, `WAIT HTTP`).

### Home mode behavior (without OBD adapter)

In `home` mode, missing OBD/serial adapter errors are intentionally shown as a friendly info state (`HOME` / `NO OBD`) instead of a hard red-style error screen.  
Real ECU errors in car operation still keep `ERR` priority.

## Dependencies

```bash
source .venv/bin/activate
pip install -r requirements-oled.txt
```

## Run

```bash
source .venv/bin/activate
python tools/oled_status.py
```

**Runs on the Raspberry Pi** with I2C enabled and `requirements-oled.txt` installed. On a normal Linux desktop the `board` / Blinka stack is absent by design — use the Pi (or a board with the same deps) to exercise the display.

### Typography (larger, full-area)

The script prefers **TrueType** for maximum readable size on 128×32:

- Default search order: `ECU_OLED_FONT` (if set), then `/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`, then `DejaVuSans.ttf` (typical on Raspberry Pi OS).
- If no `.ttf` is found, it falls back to Pillow’s small bitmap `load_default()`.
- Per screen, font **point size** is chosen so lines fit width and height (`textbbox`-based stacking, minimal side margins).

Optional tuning:

- `ECU_OLED_FONT` — path to a `.ttf` (e.g. another bold sans).
- `ECU_OLED_TTF_MAX` / `ECU_OLED_TTF_MIN` — clamp largest/smallest point size tried (defaults 26 / 8).
- `ECU_OLED_MARGIN_X` — horizontal inset in pixels (default `1`).
- `ECU_OLED_LINE_GAP` — gap between stacked lines (default `1`).
- `ECU_OLED_PAD_Y` — reserved pixels at the bottom when fitting text (default `2`), reduces clipping of descenders on the live two-line layout.
- `ECU_OLED_MIN_GAP_Y` — minimum vertical gap between first and second line in top/bottom two-line layouts (`LIVE`, `ERR`), default `2`.

Install fonts on Lite if needed: `sudo apt install -y fonts-dejavu-core`

Optional environment variables:

- `ECU_OLED_URL` (default `http://127.0.0.1:${ECU_HTTP_PORT:-1994}/api/status`)
- `ECU_OLED_POLL_S` (default `0.8`)
- `ECU_OLED_BOOTING_S` (default `4.0`)
- `ECU_OLED_HTTP_TIMEOUT_S` (default `1.2`)
- `ECU_OLED_TEST_CYCLE=1` (still supported) — same as `--test` (overridden if you pass a single-screen flag like `--test-live`)
- `ECU_OLED_TEST_STEP_S` — **base** seconds per test slide (default `4.0`); each phase uses a multiplier so nothing “flashes” too briefly (overridable with `--test-step-s`)
- `ECU_OLED_TEST_BLANK_BEFORE_S` — seconds of **fully blank** display before the first slide (default `1.0`; CLI `--test-blank-s`)
- `ECU_OLED_TEST_DWELL_MIN_S` — minimum dwell per slide after multipliers (default `1.25`)
- `ECU_OLED_TEST_PHASE_MULT` — optional six comma-separated multipliers for phases `BOOTING,HOME_NO_OBD,ECU_car,LIVE,ERR,ECU_home` (defaults built in)
- **Display lock** (default on): only one `oled_status.py` may use the panel. Lock file: `ECU_OLED_LOCK_PATH` (default `/tmp/pib4ecu-oled-display.lock`). If a second instance starts while `oled-display.service` is running, it exits with a hint to `sudo systemctl stop oled-display`. Emergency override: `ECU_OLED_LOCK_DISABLED=1` (not recommended).

### Status test mode (for layout tuning)

On the Pi, from the repo directory:

**One screen at a time** (stays until Ctrl+C; best for tuning typography):

```bash
source .venv/bin/activate
python tools/oled_status.py --test-live
# or: python tools/oled_status.py --test-screen live
# other screens: booting, wait_http, home_no_obd, ecu_connect_car, err, ecu_connect_home
# shorthand: --test-booting, --test-wait-http, --test-home-no-obd, --test-ecu-car, --test-err, --test-ecu-home
```

**Full cycle** (all slides in rotation):

```bash
python tools/oled_status.py --test
# optional: python tools/oled_status.py --test --test-step-s 5 --test-blank-s 1.5
```

Cycle order: `BOOTING`, `HOME/NO OBD`, `ECU CONNECT` (car), `LIVE`, `ERR`, `ECU CONNECT` (home).  
`WAIT HTTP` is only available as a single screen (`--test-wait-http`), not in the auto cycle.

In **test** mode (`--test` / `--test-screen` / shorthand flags), **network mode for OLED logic comes only from the fixture** (`net_mode` in the fake payload). The file `/etc/pib4ecu/net-mode` on the Pi is **not** read, so host `home`/`auto` cannot override what you are trying to preview. Normal polling from `/api/status` still uses the marker file when the API omits `net_mode`.

Live ECU values and `ERR` details use a **top/bottom anchored two-line layout**: first line near top, second line near bottom, with a guaranteed minimum gap (`ECU_OLED_MIN_GAP_Y`) for readability.

If line 2 still clips on your panel, try:
- increase `ECU_OLED_PAD_Y` (e.g. `3` or `4`)
- increase `ECU_OLED_MIN_GAP_Y` slightly
- reduce max font: `ECU_OLED_TTF_MAX=24` (or lower)

The script **clears the panel** for `ECU_OLED_TEST_BLANK_BEFORE_S` before the cycle (so e.g. `HOME/NO OBD` from normal mode is gone cleanly). On exit (**Ctrl+C** or process end) it **clears the panel again**; turn normal operation back on with:

```bash
sudo systemctl start oled-display
```

**systemd without editing unit files:** stop the normal service, run test in a shell, then start the service again when done:

```bash
sudo systemctl stop oled-display
cd /path/to/piB4ECU && source .venv/bin/activate && python tools/oled_status.py --test
# Ctrl+C when finished
sudo systemctl start oled-display
```

If the picture **flickers** between a test layout and normal “HOME / HTTP / …” content, **two processes are usually writing the same I2C OLED** (service + manual test). Stop the service first, or rely on the lock: the second process will exit unless you disabled it.

Do **not** put `ECU_OLED_TEST_CYCLE=1` (or `--test`) in `oled-display.service` for day-to-day use — that forces a rotating test pattern instead of live data.

## systemd (example)

Create `/etc/systemd/system/oled-display.service`:

```ini
[Unit]
Description=piB4ECU OLED mini display
After=local-fs.target
Wants=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/piB4ECU
Environment=ECU_HTTP_PORT=1994
# Do not add ECU_OLED_TEST_CYCLE here for normal operation.
ExecStart=/home/pi/piB4ECU/.venv/bin/python tools/oled_status.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable oled-display
sudo systemctl start oled-display
```

## Value meaning and limits

- Fault-memory readout is currently not fully reliable in this project.
  The OLED view does not depend on fault-memory details.
- Live consumption (`live_lph`, `live_l_per_100km`) is currently model-based and calibration-dependent.
  Values are already useful as trend/live indicator, but absolute precision is still improving.
