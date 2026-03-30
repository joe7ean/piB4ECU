# OLED Mini Display (SSD1306 128x32)

This guide covers software setup and runtime behavior for the OLED status screen.
Hardware wiring lives in `docs/OLED_HARDWARE.md`.

## What it shows

Display priority is intentionally simple for a tiny 128x32 screen:

1. Error first (`engine_error`)
2. If not connected: `ECU CONNECT`
3. If connected and no error:
   - top row distributed: coolant (left) and voltage (right)
   - center rows: live fuel consumption (`L100` preferred, fallback `Lh`)

Boot/wait states are centered text (`BOOTING`, `WAIT HTTP`).

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

Optional environment variables:

- `ECU_OLED_URL` (default `http://127.0.0.1:${ECU_HTTP_PORT:-1994}/api/status`)
- `ECU_OLED_POLL_S` (default `0.8`)
- `ECU_OLED_BOOTING_S` (default `4.0`)
- `ECU_OLED_HTTP_TIMEOUT_S` (default `1.2`)

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
