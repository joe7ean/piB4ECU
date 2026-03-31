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

Install fonts on Lite if needed: `sudo apt install -y fonts-dejavu-core`

Optional environment variables:

- `ECU_OLED_URL` (default `http://127.0.0.1:${ECU_HTTP_PORT:-1994}/api/status`)
- `ECU_OLED_POLL_S` (default `0.8`)
- `ECU_OLED_BOOTING_S` (default `4.0`)
- `ECU_OLED_HTTP_TIMEOUT_S` (default `1.2`)
- `ECU_OLED_TEST_CYCLE=1` (still supported) — same as `--test`
- `ECU_OLED_TEST_STEP_S=2.0` — per-screen duration in test mode (overridable with `--test-step-s`)

### Status test mode (for layout tuning)

On the Pi, from the repo directory:

```bash
source .venv/bin/activate
python tools/oled_status.py --test
# optional: python tools/oled_status.py --test --test-step-s 2.0
```

Cycle includes: `BOOTING`, `HOME/NO OBD`, `ECU CONNECT`, `LIVE`, and `ERR`.

**systemd without editing unit files:** stop the normal service, run test in a shell, then start the service again when done:

```bash
sudo systemctl stop oled-display
cd /path/to/piB4ECU && source .venv/bin/activate && python tools/oled_status.py --test
# Ctrl+C when finished
sudo systemctl start oled-display
```

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
