#!/usr/bin/env python3
"""
SSD1306 128x32 mini status display for piB4ECU.

Layout goals:
- Large TrueType when available (DejaVu Bold on Pi OS); fallback bitmap font.
- Full width / height: textbbox-based stacking, minimal margins.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import suppress
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


OLED_WIDTH = 128
OLED_HEIGHT = 32
LEFT_RIGHT_MARGIN = int(os.environ.get("ECU_OLED_MARGIN_X", "1"))
LINE_GAP = int(os.environ.get("ECU_OLED_LINE_GAP", "1"))
OLED_TTF_MAX_PT = int(os.environ.get("ECU_OLED_TTF_MAX", "26"))
OLED_TTF_MIN_PT = int(os.environ.get("ECU_OLED_TTF_MIN", "8"))
POLL_INTERVAL_S = float(os.environ.get("ECU_OLED_POLL_S", "0.8"))
BOOTING_SECONDS = float(os.environ.get("ECU_OLED_BOOTING_S", "4.0"))
HTTP_TIMEOUT_S = float(os.environ.get("ECU_OLED_HTTP_TIMEOUT_S", "1.2"))

ECU_HTTP_PORT = os.environ.get("ECU_HTTP_PORT", "1994")
DEFAULT_URL = f"http://127.0.0.1:{ECU_HTTP_PORT}/api/status"
STATUS_URL = os.environ.get("ECU_OLED_URL", DEFAULT_URL)
NET_MODE_FILE = Path("/etc/pib4ecu/net-mode")
_TEST_FLAG_VALUES = {"1", "true", "yes", "on"}
# Base seconds per test slide; each phase multiplies this (see _test_phase_dwell_s).
_DEFAULT_TEST_STEP_S = float(os.environ.get("ECU_OLED_TEST_STEP_S", "4.0"))
_TEST_DWELL_MIN_S = float(os.environ.get("ECU_OLED_TEST_DWELL_MIN_S", "1.25"))
# Pause with display fully blank before the first test frame (clean switch from prior content).
_TEST_BLANK_BEFORE_S = float(os.environ.get("ECU_OLED_TEST_BLANK_BEFORE_S", "1.0"))
# Relative length per phase (cycle 0..5): BOOTING, HOME/NO OBD, ECU car, LIVE, ERR, ECU home
_TEST_PHASE_MULT_DEFAULT: tuple[float, ...] = (1.35, 1.05, 1.05, 1.45, 1.2, 1.05)

# Fake API payloads for layout checks (same data as the former cycle steps 1..5).
_TEST_FIXTURE_HOME_NO_OBD: dict = {
    "engine_connected": False,
    "engine_error": "could not open port /dev/ttyUSB0",
    "engine_data": {},
    "trip": {},
    "net_mode": "home",
}
_TEST_FIXTURE_ECU_CONNECT_CAR: dict = {
    "engine_connected": False,
    "engine_error": None,
    "engine_data": {},
    "trip": {},
    "net_mode": "car",
}
_TEST_FIXTURE_LIVE: dict = {
    "engine_connected": True,
    "engine_error": None,
    "engine_data": {
        "Kühlmitteltemperatur": {"value": 87, "unit": "C"},
        "Spannung": {"value": 14.1, "unit": "V"},
    },
    "trip": {"live_l_per_100km": 7.1, "live_lph": 2.9, "speed_kmh": 41},
    "net_mode": "car",
}
_TEST_FIXTURE_ERR: dict = {
    "engine_connected": True,
    "engine_error": "Timeout beim Lesen — ECU antwortet nicht",
    "engine_data": {},
    "trip": {},
    "net_mode": "car",
}
_TEST_FIXTURE_ECU_CONNECT_HOME: dict = {
    "engine_connected": False,
    "engine_error": None,
    "engine_data": {},
    "trip": {},
    "net_mode": "home",
}

# Order used by --test full cycle (no wait_http in rotation).
_TEST_CYCLE_SCREENS: tuple[str, ...] = (
    "booting",
    "home_no_obd",
    "ecu_connect_car",
    "live",
    "err",
    "ecu_connect_home",
)

TEST_SCREEN_CHOICES: tuple[str, ...] = (
    "booting",
    "wait_http",
    "home_no_obd",
    "ecu_connect_car",
    "live",
    "err",
    "ecu_connect_home",
)


def _env_test_cycle_enabled() -> bool:
    return os.environ.get("ECU_OLED_TEST_CYCLE", "").strip().lower() in _TEST_FLAG_VALUES


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="piB4ECU SSD1306 status display (runs on Raspberry Pi with I2C + Blinka).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Single test screens (hold until Ctrl+C): --test-screen booting | wait_http | home_no_obd | "
            "ecu_connect_car | live | err | ecu_connect_home — or shorthand --test-booting, --test-live, …\n"
            "Full cycle: --test (or env ECU_OLED_TEST_CYCLE=1). Single-screen flags override env cycle."
        ),
    )
    test_x = p.add_mutually_exclusive_group()
    test_x.add_argument(
        "--test",
        action="store_true",
        help="Cycle through all fake states (no HTTP). Timing: --test-step-s / ECU_OLED_TEST_STEP_S.",
    )
    test_x.add_argument(
        "--test-screen",
        choices=TEST_SCREEN_CHOICES,
        default=None,
        dest="test_screen",
        metavar="NAME",
        help="Show one fixture and keep it until Ctrl+C.",
    )
    for flag, name in (
        ("--test-booting", "booting"),
        ("--test-wait-http", "wait_http"),
        ("--test-home-no-obd", "home_no_obd"),
        ("--test-ecu-car", "ecu_connect_car"),
        ("--test-live", "live"),
        ("--test-err", "err"),
        ("--test-ecu-home", "ecu_connect_home"),
    ):
        test_x.add_argument(flag, dest="test_screen", action="store_const", const=name, help=f"Same as --test-screen {name}.")
    p.add_argument(
        "--test-step-s",
        type=float,
        default=None,
        metavar="SEC",
        help=f"Base seconds per --test cycle slide (default {_DEFAULT_TEST_STEP_S}); ignored for single --test-screen (uses poll interval).",
    )
    p.add_argument(
        "--test-blank-s",
        type=float,
        default=None,
        metavar="SEC",
        help=f"Show blank display this long before test output (default {_TEST_BLANK_BEFORE_S}; env ECU_OLED_TEST_BLANK_BEFORE_S).",
    )
    return p.parse_args(argv)


def _fetch_status(url: str, timeout: float) -> Optional[dict]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8")
        return json.loads(payload)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _read_net_mode() -> str:
    try:
        mode = NET_MODE_FILE.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return "unknown"
    if mode in {"car", "home", "usb", "auto"}:
        return mode
    return "unknown"


def _resolve_ttf_path() -> Optional[str]:
    env = os.environ.get("ECU_OLED_FONT", "").strip()
    candidates = []
    if env:
        candidates.append(env)
    candidates.extend(
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for p in candidates:
        if p and Path(p).is_file():
            return p
    return None


def _looks_like_no_obd_error(err: str) -> bool:
    text = err.lower()
    patterns = (
        "could not open port",
        "no such file or directory",
        "/dev/ttyusb",
        "/dev/serial/by-id",
    )
    return any(p in text for p in patterns)


def _parse_test_phase_mults() -> tuple[float, ...]:
    raw = os.environ.get("ECU_OLED_TEST_PHASE_MULT", "").strip()
    if not raw:
        return _TEST_PHASE_MULT_DEFAULT
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    try:
        vals = tuple(float(x) for x in parts)
    except ValueError:
        return _TEST_PHASE_MULT_DEFAULT
    if len(vals) != 6:
        return _TEST_PHASE_MULT_DEFAULT
    return vals


def _test_phase_dwell_s(phase_index: int, base_step_s: float) -> float:
    mults = _parse_test_phase_mults()
    m = mults[phase_index % 6]
    return max(_TEST_DWELL_MIN_S, float(base_step_s) * m)


def _oled_blank(display: object) -> None:
    display.fill(0)
    display.show()


def _test_screen_args(screen: str) -> tuple[Optional[dict], bool]:
    """Return (status_dict_or_None, booting) for _render_status."""
    if screen == "booting":
        return None, True
    if screen == "wait_http":
        return None, False
    fixtures: dict[str, dict] = {
        "home_no_obd": _TEST_FIXTURE_HOME_NO_OBD,
        "ecu_connect_car": _TEST_FIXTURE_ECU_CONNECT_CAR,
        "live": _TEST_FIXTURE_LIVE,
        "err": _TEST_FIXTURE_ERR,
        "ecu_connect_home": _TEST_FIXTURE_ECU_CONNECT_HOME,
    }
    data = fixtures[screen]
    return data, False


def _test_cycle_phase(step: int) -> tuple[Optional[dict], bool]:
    name = _TEST_CYCLE_SCREENS[step % len(_TEST_CYCLE_SCREENS)]
    return _test_screen_args(name)


def _line_metrics(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    return _line_metrics(draw, text, font)


def _trim_to_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    if not text:
        return ""
    if _measure_text(draw, text, font)[0] <= max_width:
        return text
    ellipsis = "…"
    out = text
    while out and _measure_text(draw, out + ellipsis, font)[0] > max_width:
        out = out[:-1]
    return (out + ellipsis) if out else ellipsis


def _try_truetype(path: str, size: int) -> Optional[ImageFont.FreeTypeFont]:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return None


def max_font_size_for_lines(
    draw: ImageDraw.ImageDraw,
    ttf_path: str,
    lines: list[str],
    max_width: int,
    max_height: int,
    gap: int = LINE_GAP,
    min_pt: int = OLED_TTF_MIN_PT,
    max_pt: int = OLED_TTF_MAX_PT,
) -> Optional[tuple[ImageFont.FreeTypeFont, int]]:
    """Largest font size where every line fits max_width and total height <= max_height."""
    for pt in range(max_pt, min_pt - 1, -1):
        font = _try_truetype(ttf_path, pt)
        if font is None:
            continue
        heights: list[int] = []
        widths: list[int] = []
        for line in lines:
            w, h = _line_metrics(draw, line, font)
            heights.append(h)
            widths.append(w)
        total_h = sum(heights) + gap * max(0, len(lines) - 1)
        if max(widths) <= max_width and total_h <= max_height:
            return font, pt
    return None


def _draw_lines_centered_vertical(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.ImageFont,
    gap: int = LINE_GAP,
) -> None:
    heights = [_line_metrics(draw, ln, font)[1] for ln in lines]
    widths = [_line_metrics(draw, ln, font)[0] for ln in lines]
    total_h = sum(heights) + gap * max(0, len(lines) - 1)
    y = max(0, (OLED_HEIGHT - total_h) // 2)
    for i, line in enumerate(lines):
        w = widths[i]
        x = max(0, (OLED_WIDTH - w) // 2)
        draw.text((x, y), line, font=font, fill=255)
        y += heights[i] + gap


def _draw_single_line_centered_fit(
    draw: ImageDraw.ImageDraw,
    text: str,
    ttf_path: Optional[str],
    bitmap_font: ImageFont.ImageFont,
    max_width: int,
    max_height: int,
) -> None:
    inner_w = min(max_width, OLED_WIDTH - 2 * LEFT_RIGHT_MARGIN)
    if ttf_path:
        for pt in range(OLED_TTF_MAX_PT, OLED_TTF_MIN_PT - 1, -1):
            font = _try_truetype(ttf_path, pt)
            if font is None:
                continue
            w, h = _line_metrics(draw, text, font)
            if w <= inner_w and h <= max_height:
                x = max(0, (OLED_WIDTH - w) // 2)
                y = max(0, (OLED_HEIGHT - h) // 2)
                draw.text((x, y), text, font=font, fill=255)
                return
    font = bitmap_font
    w, h = _line_metrics(draw, text, font)
    x = max(0, (OLED_WIDTH - w) // 2)
    y = max(0, (OLED_HEIGHT - h) // 2)
    draw.text((x, y), text, font=font, fill=255)


def _draw_home_no_obd(draw: ImageDraw.ImageDraw, ttf_path: Optional[str], bitmap_font: ImageFont.ImageFont) -> None:
    one_line = "HOME  NO OBD"
    inner_w = OLED_WIDTH - 2 * LEFT_RIGHT_MARGIN
    if ttf_path:
        for pt in range(OLED_TTF_MAX_PT, OLED_TTF_MIN_PT - 1, -1):
            font = _try_truetype(ttf_path, pt)
            if font is None:
                continue
            w, h = _line_metrics(draw, one_line, font)
            if w <= inner_w and h <= OLED_HEIGHT:
                x = max(0, (OLED_WIDTH - w) // 2)
                y = max(0, (OLED_HEIGHT - h) // 2)
                draw.text((x, y), one_line, font=font, fill=255)
                return
        pair = max_font_size_for_lines(draw, ttf_path, ["HOME", "NO OBD"], inner_w, OLED_HEIGHT)
        if pair:
            _draw_lines_centered_vertical(draw, ["HOME", "NO OBD"], pair[0])
            return
    _draw_lines_centered_vertical(draw, ["HOME", "NO OBD"], bitmap_font)


def _draw_err_block(
    draw: ImageDraw.ImageDraw,
    message: str,
    ttf_path: Optional[str],
    bitmap_font: ImageFont.ImageFont,
) -> None:
    title = "ERR"
    inner_w = OLED_WIDTH - 2 * LEFT_RIGHT_MARGIN
    if ttf_path:
        for t_pt in range(min(22, OLED_TTF_MAX_PT), OLED_TTF_MIN_PT + 2, -1):
            t_font = _try_truetype(ttf_path, t_pt)
            if t_font is None:
                continue
            w_t, h_t = _line_metrics(draw, title, t_font)
            if w_t > OLED_WIDTH - 2:
                continue
            rem_h = OLED_HEIGHT - h_t - LINE_GAP
            if rem_h < OLED_TTF_MIN_PT:
                continue
            for m_pt in range(min(t_pt - 1, 15), OLED_TTF_MIN_PT - 1, -1):
                m_font = _try_truetype(ttf_path, m_pt)
                if m_font is None:
                    continue
                msg = _trim_to_width(draw, message.strip(), m_font, inner_w)
                w_m, h_m = _line_metrics(draw, msg, m_font)
                if h_m > rem_h or w_m > inner_w:
                    continue
                total = h_t + LINE_GAP + h_m
                if total <= OLED_HEIGHT:
                    y0 = max(0, (OLED_HEIGHT - total) // 2)
                    x_t = max(0, (OLED_WIDTH - w_t) // 2)
                    draw.text((x_t, y0), title, font=t_font, fill=255)
                    y1 = y0 + h_t + LINE_GAP
                    x_m = max(0, (OLED_WIDTH - w_m) // 2)
                    draw.text((x_m, y1), msg, font=m_font, fill=255)
                    return
    font = bitmap_font
    msg = _trim_to_width(draw, message.strip(), font, inner_w)
    lines = [title, msg]
    _draw_lines_centered_vertical(draw, lines, font)


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


def _consumption_primary_compact(trip: dict) -> str:
    l100 = trip.get("live_l_per_100km")
    if isinstance(l100, (int, float)):
        return f"{float(l100):.1f}/100"
    lph = trip.get("live_lph")
    if isinstance(lph, (int, float)):
        return f"{float(lph):.1f}Lh"
    return "-/100"


def _consumption_extra_same_line(trip: dict) -> str:
    l100 = trip.get("live_l_per_100km")
    lph = trip.get("live_lph")
    if isinstance(l100, (int, float)) and isinstance(lph, (int, float)):
        return f"{float(lph):.1f}Lh"
    speed = trip.get("speed_kmh")
    if isinstance(speed, (int, float)):
        return f"{float(speed):.0f}kmh"
    return ""


def _render_live_two_row(
    draw: ImageDraw.ImageDraw,
    trip: dict,
    engine_data: dict,
    ttf_path: Optional[str],
    bitmap_font: ImageFont.ImageFont,
) -> None:
    left, right = _line_live_top(
        (engine_data.get("Kühlmitteltemperatur") or {}).get("value"),
        (engine_data.get("Spannung") or {}).get("value"),
    )
    primary = _consumption_primary_compact(trip)
    extra = _consumption_extra_same_line(trip)
    inner = OLED_WIDTH - 2 * LEFT_RIGHT_MARGIN

    if ttf_path:
        for pt in range(OLED_TTF_MAX_PT, OLED_TTF_MIN_PT - 1, -1):
            font = _try_truetype(ttf_path, pt)
            if font is None:
                continue
            lw, lh = _line_metrics(draw, left, font)
            rw, rh = _line_metrics(draw, right, font)
            h1 = max(lh, rh)
            if lw + rw > inner:
                continue
            line2 = f"{primary} {extra}".strip() if extra else primary
            cw, ch = _line_metrics(draw, line2, font)
            if cw > inner:
                line2 = primary
                cw, ch = _line_metrics(draw, line2, font)
            if cw > inner:
                line2 = _trim_to_width(draw, line2, font, inner)
                cw, ch = _line_metrics(draw, line2, font)
            if h1 + LINE_GAP + ch > OLED_HEIGHT:
                continue
            block_h = h1 + LINE_GAP + ch
            y_top = max(0, (OLED_HEIGHT - block_h) // 2)
            draw.text((LEFT_RIGHT_MARGIN, y_top), left, font=font, fill=255)
            draw.text((OLED_WIDTH - LEFT_RIGHT_MARGIN - rw, y_top), right, font=font, fill=255)
            y2 = y_top + h1 + LINE_GAP
            draw.text((max(0, (OLED_WIDTH - cw) // 2), y2), line2, font=font, fill=255)
            return

    font = bitmap_font
    lw, lh = _line_metrics(draw, left, font)
    rw, rh = _line_metrics(draw, right, font)
    h1 = max(lh, rh)
    line2 = f"{primary} {extra}".strip() if extra else primary
    line2 = _trim_to_width(draw, line2, font, inner)
    cw, ch = _line_metrics(draw, line2, font)
    block_h = h1 + LINE_GAP + ch
    y_top = max(0, (OLED_HEIGHT - block_h) // 2)
    draw.text((LEFT_RIGHT_MARGIN, y_top), left, font=font, fill=255)
    draw.text((OLED_WIDTH - LEFT_RIGHT_MARGIN - rw, y_top), right, font=font, fill=255)
    y2 = y_top + h1 + LINE_GAP
    draw.text((max(0, (OLED_WIDTH - cw) // 2), y2), line2, font=font, fill=255)


def _render_status(
    display: object,
    ttf_path: Optional[str],
    bitmap_font: ImageFont.ImageFont,
    status: Optional[dict],
    booting: bool,
    use_host_net_mode: bool = True,
) -> None:
    image = Image.new("1", (OLED_WIDTH, OLED_HEIGHT))
    draw = ImageDraw.Draw(image)

    if booting and status is None:
        _draw_single_line_centered_fit(draw, "BOOTING", ttf_path, bitmap_font, OLED_WIDTH, OLED_HEIGHT)
    elif status is None:
        _draw_single_line_centered_fit(draw, "WAIT HTTP", ttf_path, bitmap_font, OLED_WIDTH, OLED_HEIGHT)
    else:
        engine_error = status.get("engine_error")
        connected = bool(status.get("engine_connected"))
        engine_data = status.get("engine_data") or {}
        trip = status.get("trip") or {}
        if use_host_net_mode:
            raw_nm = status.get("net_mode")
            net_mode = (raw_nm if isinstance(raw_nm, str) and raw_nm.strip() else _read_net_mode()).strip().lower()
        else:
            raw_nm = status.get("net_mode")
            net_mode = raw_nm.strip().lower() if isinstance(raw_nm, str) and raw_nm.strip() else "unknown"
        is_no_obd_error = (
            isinstance(engine_error, str)
            and engine_error.strip()
            and _looks_like_no_obd_error(engine_error)
        )
        is_home_like_mode = net_mode in {"home", "auto"}
        is_home_no_obd = is_home_like_mode and is_no_obd_error

        if is_home_no_obd:
            _draw_home_no_obd(draw, ttf_path, bitmap_font)
        elif isinstance(engine_error, str) and engine_error.strip():
            _draw_err_block(draw, engine_error, ttf_path, bitmap_font)
        elif not connected:
            _draw_single_line_centered_fit(draw, "ECU CONNECT", ttf_path, bitmap_font, OLED_WIDTH, OLED_HEIGHT)
        else:
            _render_live_two_row(draw, trip, engine_data, ttf_path, bitmap_font)

    display.image(image)
    display.show()


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    test_screen: Optional[str] = args.test_screen
    test_cycle = (bool(args.test) or _env_test_cycle_enabled()) and test_screen is None
    test_mode = test_cycle or test_screen is not None
    test_step_s = args.test_step_s if args.test_step_s is not None else _DEFAULT_TEST_STEP_S
    test_blank_before_s = args.test_blank_s if args.test_blank_s is not None else _TEST_BLANK_BEFORE_S

    try:
        import board
        import busio
        import adafruit_ssd1306
    except ModuleNotFoundError as e:
        if getattr(e, "name", None) in {"board", "busio", "adafruit_ssd1306"}:
            print(
                "Missing OLED/I2C Python deps (e.g. adafruit-blinka). "
                "Install on the Pi: pip install -r requirements-oled.txt — "
                "this script does not run on a normal PC without hardware stack.",
                file=sys.stderr,
            )
            raise SystemExit(1) from e
        raise

    i2c = busio.I2C(board.SCL, board.SDA)
    display = adafruit_ssd1306.SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, i2c, addr=0x3C)
    display.fill(0)
    display.show()
    ttf_path = _resolve_ttf_path()
    bitmap_font = ImageFont.load_default()

    start = time.time()
    seen_status_once = False

    cycle_step = 0
    try:
        if test_mode:
            _oled_blank(display)
            time.sleep(max(0.0, test_blank_before_s))

        while True:
            if test_screen is not None:
                status, booting = _test_screen_args(test_screen)
                _render_status(display, ttf_path, bitmap_font, status, booting, use_host_net_mode=False)
                time.sleep(POLL_INTERVAL_S)
                continue

            if test_cycle:
                status, booting = _test_cycle_phase(cycle_step)
                phase = cycle_step % len(_TEST_CYCLE_SCREENS)
                _render_status(display, ttf_path, bitmap_font, status, booting, use_host_net_mode=False)
                cycle_step += 1
                time.sleep(_test_phase_dwell_s(phase, test_step_s))
                continue

            status = _fetch_status(STATUS_URL, HTTP_TIMEOUT_S)
            if status is not None:
                seen_status_once = True

            booting = (time.time() - start) < BOOTING_SECONDS and not seen_status_once
            _render_status(display, ttf_path, bitmap_font, status, booting, use_host_net_mode=True)
            time.sleep(POLL_INTERVAL_S)
    finally:
        if test_mode:
            with suppress(Exception):
                _oled_blank(display)


if __name__ == "__main__":
    main()
