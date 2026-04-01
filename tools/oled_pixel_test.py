#!/usr/bin/env python3
"""
SSD1306 pixel test utility for 128x32 OLED panels.

Purpose:
- Verify whether all pixels are physically present/visible.
- Detect cropped/shifted clone displays.
- Distinguish layout issues from hardware panel geometry.
"""

from __future__ import annotations

import argparse
import sys
import time
from contextlib import suppress

from PIL import Image, ImageDraw


OLED_WIDTH = 128
OLED_HEIGHT = 32


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Low-level SSD1306 pixel test patterns.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python tools/oled_pixel_test.py --mode on\n"
            "  python tools/oled_pixel_test.py --mode blink --interval 0.4\n"
            "  python tools/oled_pixel_test.py --mode rows --interval 0.08\n"
            "  python tools/oled_pixel_test.py --mode cols --interval 0.04\n"
            "  python tools/oled_pixel_test.py --mode pixel --x 127 --y 31\n"
        ),
    )
    p.add_argument(
        "--mode",
        choices=("on", "off", "blink", "checker", "border", "rows", "cols", "pixel", "walk"),
        default="blink",
        help="Test pattern mode.",
    )
    p.add_argument("--interval", type=float, default=0.25, help="Seconds between frames.")
    p.add_argument("--hold", type=float, default=1.2, help="Seconds to hold static modes.")
    p.add_argument("--x", type=int, default=0, help="X for --mode pixel (0..127).")
    p.add_argument("--y", type=int, default=0, help="Y for --mode pixel (0..31).")
    p.add_argument("--count", type=int, default=0, help="Frame count for loop modes (0=infinite).")
    p.add_argument("--addr", default="0x3c", help="I2C address, default 0x3c.")
    return p.parse_args()


def _mk_image(fill: int = 0) -> Image.Image:
    return Image.new("1", (OLED_WIDTH, OLED_HEIGHT), color=fill)


def _show(display: object, image: Image.Image) -> None:
    display.image(image)
    display.show()


def _all_on() -> Image.Image:
    return _mk_image(fill=1)


def _all_off() -> Image.Image:
    return _mk_image(fill=0)


def _checker(step: int = 2) -> Image.Image:
    image = _mk_image(fill=0)
    draw = ImageDraw.Draw(image)
    for y in range(0, OLED_HEIGHT, step):
        for x in range(0, OLED_WIDTH, step):
            if ((x // step) + (y // step)) % 2 == 0:
                draw.rectangle((x, y, min(x + step - 1, OLED_WIDTH - 1), min(y + step - 1, OLED_HEIGHT - 1)), fill=1)
    return image


def _border() -> Image.Image:
    image = _mk_image(fill=0)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, OLED_WIDTH - 1, OLED_HEIGHT - 1), outline=1, fill=0)
    # Extra guide lines near edges to reveal clipping.
    draw.line((0, 1, OLED_WIDTH - 1, 1), fill=1)
    draw.line((0, OLED_HEIGHT - 2, OLED_WIDTH - 1, OLED_HEIGHT - 2), fill=1)
    draw.line((1, 0, 1, OLED_HEIGHT - 1), fill=1)
    draw.line((OLED_WIDTH - 2, 0, OLED_WIDTH - 2, OLED_HEIGHT - 1), fill=1)
    return image


def _single_row(y: int) -> Image.Image:
    image = _mk_image(fill=0)
    draw = ImageDraw.Draw(image)
    yy = max(0, min(OLED_HEIGHT - 1, y))
    draw.line((0, yy, OLED_WIDTH - 1, yy), fill=1)
    return image


def _single_col(x: int) -> Image.Image:
    image = _mk_image(fill=0)
    draw = ImageDraw.Draw(image)
    xx = max(0, min(OLED_WIDTH - 1, x))
    draw.line((xx, 0, xx, OLED_HEIGHT - 1), fill=1)
    return image


def _single_pixel(x: int, y: int) -> Image.Image:
    image = _mk_image(fill=0)
    draw = ImageDraw.Draw(image)
    xx = max(0, min(OLED_WIDTH - 1, x))
    yy = max(0, min(OLED_HEIGHT - 1, y))
    draw.point((xx, yy), fill=1)
    # Add a tiny crosshair to make the pixel location visible to the eye.
    if xx > 0:
        draw.point((xx - 1, yy), fill=1)
    if xx < OLED_WIDTH - 1:
        draw.point((xx + 1, yy), fill=1)
    if yy > 0:
        draw.point((xx, yy - 1), fill=1)
    if yy < OLED_HEIGHT - 1:
        draw.point((xx, yy + 1), fill=1)
    return image


def main() -> None:
    args = _parse_args()

    try:
        import board
        import busio
        import adafruit_ssd1306
    except ModuleNotFoundError as e:
        print(
            "Missing OLED/I2C deps. Install on Pi: pip install -r requirements-oled.txt",
            file=sys.stderr,
        )
        raise SystemExit(1) from e

    addr = int(str(args.addr), 16)
    i2c = busio.I2C(board.SCL, board.SDA)
    display = adafruit_ssd1306.SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, i2c, addr=addr)

    frame = 0
    try:
        if args.mode == "on":
            _show(display, _all_on())
            time.sleep(max(0.05, args.hold))
            return
        if args.mode == "off":
            _show(display, _all_off())
            time.sleep(max(0.05, args.hold))
            return
        if args.mode == "checker":
            _show(display, _checker())
            time.sleep(max(0.05, args.hold))
            return
        if args.mode == "border":
            _show(display, _border())
            time.sleep(max(0.05, args.hold))
            return
        if args.mode == "pixel":
            _show(display, _single_pixel(args.x, args.y))
            time.sleep(max(0.05, args.hold))
            return

        while True:
            if args.mode == "blink":
                _show(display, _all_on() if frame % 2 == 0 else _all_off())
            elif args.mode == "rows":
                _show(display, _single_row(frame % OLED_HEIGHT))
            elif args.mode == "cols":
                _show(display, _single_col(frame % OLED_WIDTH))
            elif args.mode == "walk":
                idx = frame % (OLED_WIDTH * OLED_HEIGHT)
                x = idx % OLED_WIDTH
                y = idx // OLED_WIDTH
                _show(display, _single_pixel(x, y))

            frame += 1
            if args.count > 0 and frame >= args.count:
                break
            time.sleep(max(0.01, args.interval))
    finally:
        with suppress(Exception):
            _show(display, _all_off())


if __name__ == "__main__":
    main()
