#!/usr/bin/env python3
"""
SSD1306 128x32 mini status display for piB4ECU.

Layout goals:
- Distributed top row for coolant/voltage
- Centered boot/wait/error/live consumption lines
"""

import json
import os
import time
import urllib.error
import urllib.request
from typing import Optional

import board
import busio
import adafruit_ssd1306
from PIL import Image, ImageDraw, ImageFont


OLED_WIDTH = 128
OLED_HEIGHT = 32
LEFT_RIGHT_MARGIN = 2
POLL_INTERVAL_S = float(os.environ.get("ECU_OLED_POLL_S", "0.8"))
BOOTING_SECONDS = float(os.environ.get("ECU_OLED_BOOTING_S", "4.0"))
HTTP_TIMEOUT_S = float(os.environ.get("ECU_OLED_HTTP_TIMEOUT_S", "1.2"))

ECU_HTTP_PORT = os.environ.get("ECU_HTTP_PORT", "8080")
DEFAULT_URL = f"http://127.0.0.1:{ECU_HTTP_PORT}/api/status"
STATUS_URL = os.environ.get("ECU_OLED_URL", DEFAULT_URL)


def _fetch_status(url: str, timeout: float) -> Optional[dict]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8")
        return json.loads(payload)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _trim_to_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    if not text:
        return ""
    if _measure_text(draw, text, font)[0] <= max_width:
        return text
    ellipsis = "..."
    out = text
    while out and _measure_text(draw, out + ellipsis, font)[0] > max_width:
        out = out[:-1]
    return (out + ellipsis) if out else ellipsis


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    font: ImageFont.ImageFont,
):
    width, _ = _measure_text(draw, text, font)
    x = max(0, (OLED_WIDTH - width) // 2)
    draw.text((x, y), text, font=font, fill=255)


def _format_number(value: object, digits: int = 1) -> str:
    if isinstance(value, (int, float)):
        if digits <= 0:
            return str(int(round(float(value), 0)))
        return f"{float(value):.{digits}f}"
    return "-"


def _line_live_top(coolant: object, voltage: object) -> tuple[str, str]:
    left = f"{_format_number(coolant, 0)}C"
    right = f"{_format_number(voltage, 1)}V"
    return left, right


def _line_consumption_main(trip: dict) -> str:
    l100 = trip.get("live_l_per_100km")
    if isinstance(l100, (int, float)):
        return f"{float(l100):.1f} L100"
    lph = trip.get("live_lph")
    if isinstance(lph, (int, float)):
        return f"{float(lph):.1f} Lh"
    return "- L100"


def _line_consumption_secondary(trip: dict) -> str:
    l100 = trip.get("live_l_per_100km")
    lph = trip.get("live_lph")
    if isinstance(l100, (int, float)) and isinstance(lph, (int, float)):
        return f"{float(lph):.1f} Lh"
    speed = trip.get("speed_kmh")
    if isinstance(speed, (int, float)):
        return f"{float(speed):.0f} kmh"
    return ""


def _render_status(display: adafruit_ssd1306.SSD1306_I2C, font: ImageFont.ImageFont, status: Optional[dict], booting: bool):
    image = Image.new("1", (OLED_WIDTH, OLED_HEIGHT))
    draw = ImageDraw.Draw(image)

    if booting and status is None:
        _draw_centered(draw, 12, "BOOTING", font)
    elif status is None:
        _draw_centered(draw, 12, "WAIT HTTP", font)
    else:
        engine_error = status.get("engine_error")
        connected = bool(status.get("engine_connected"))
        engine_data = status.get("engine_data") or {}
        trip = status.get("trip") or {}

        if isinstance(engine_error, str) and engine_error.strip():
            _draw_centered(draw, 0, "ERR", font)
            msg = _trim_to_width(draw, engine_error.strip(), font, OLED_WIDTH - 4)
            _draw_centered(draw, 12, msg, font)
        elif not connected:
            _draw_centered(draw, 12, "ECU CONNECT", font)
        else:
            coolant = (engine_data.get("Kühlmitteltemperatur") or {}).get("value")
            voltage = (engine_data.get("Spannung") or {}).get("value")
            left, right = _line_live_top(coolant, voltage)
            left = _trim_to_width(draw, left, font, 56)
            right = _trim_to_width(draw, right, font, 56)

            draw.text((LEFT_RIGHT_MARGIN, 0), left, font=font, fill=255)
            right_w, _ = _measure_text(draw, right, font)
            draw.text((OLED_WIDTH - LEFT_RIGHT_MARGIN - right_w, 0), right, font=font, fill=255)

            line_main = _trim_to_width(draw, _line_consumption_main(trip), font, OLED_WIDTH - 4)
            _draw_centered(draw, 10, line_main, font)

            line_second = _line_consumption_secondary(trip)
            if line_second:
                _draw_centered(draw, 20, _trim_to_width(draw, line_second, font, OLED_WIDTH - 4), font)

    display.image(image)
    display.show()


def main():
    i2c = busio.I2C(board.SCL, board.SDA)
    display = adafruit_ssd1306.SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, i2c, addr=0x3C)
    display.fill(0)
    display.show()
    font = ImageFont.load_default()

    start = time.time()
    seen_status_once = False

    while True:
        status = _fetch_status(STATUS_URL, HTTP_TIMEOUT_S)
        if status is not None:
            seen_status_once = True

        booting = (time.time() - start) < BOOTING_SECONDS and not seen_status_once
        _render_status(display, font, status, booting)
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
