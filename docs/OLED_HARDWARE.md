# OLED Hardware Wiring (Pi Zero 2W, SSD1306 128x32)

This document covers only the electrical side.
Software setup is in `docs/OLED.md`.

## Pin mapping (I2C, 4-pin OLED)

| OLED pin | Raspberry Pi Zero 2W pin | Note |
|---|---|---|
| `GND` | `GND` (physical pin 6, 9, 14, etc.) | Ground |
| `VCC` | `3V3` (physical pin 1) | Preferred unless your module docs explicitly require/allow different |
| `SDA` | `GPIO2 / SDA1` (physical pin 3) | I2C data |
| `SCL` | `GPIO3 / SCL1` (physical pin 5) | I2C clock |

## Power and logic level notes

- Prefer `3V3` for OLED modules connected directly to Pi I2C lines.
- Some boards claim `3.3V-5V` input support. If using `5V`, verify board-level level-shifting and pull-ups in the module datasheet.
- Keep wiring short and clean to reduce I2C noise in car environment.

## Enable I2C and detect address

```bash
sudo raspi-config
# Interface Options -> I2C -> Enable

sudo apt install -y i2c-tools
sudo i2cdetect -y 1
```

Typical OLED address is `0x3c` (sometimes `0x3d`).
