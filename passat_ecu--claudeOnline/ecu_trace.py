#!/usr/bin/env python3
"""
Vordergrund-CLI: KW1281-Handshake + optionale Messwertblöcke — kein Webserver, kein Port 8000.

Beispiele:
  python ecu_trace.py
  python ecu_trace.py --port /dev/ttyUSB0 --baud 4800 --attempts 10
  python ecu_trace.py --measure 1 --attempts 3

Logs: Standard JSONL unter logs/kw1281_handshake.jsonl (override mit --log oder ECU_DIAG_LOG).

Sauber beenden: Ctrl+C im selben Terminal (ein Prozess, Vordergrund).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from kw1281 import ECU_ENGINE, KW1281, KW1281Error

_BASE = Path(__file__).resolve().parent
_DEFAULT_LOG = _BASE / "logs" / "kw1281_handshake.jsonl"


def main() -> int:
    p = argparse.ArgumentParser(description="KW1281 ECU Trace (CLI, kein HTTP)")
    p.add_argument("--port", default=os.environ.get("ECU_SERIAL_PORT", "/dev/ttyUSB0"))
    p.add_argument("--baud", type=int, default=int(os.environ.get("ECU_BAUD", "4800")))
    p.add_argument(
        "--attempts",
        type=int,
        default=int(os.environ.get("ECU_CONNECT_ATTEMPTS", "10")),
    )
    p.add_argument(
        "--log",
        default=os.environ.get("ECU_DIAG_LOG", str(_DEFAULT_LOG)),
        help="JSONL-Pfad für Handshake-Diagnosezeilen",
    )
    p.add_argument(
        "--between",
        type=float,
        default=2.0,
        help="Sekunden Pause zwischen Connect-Versuchen",
    )
    p.add_argument(
        "--measure",
        type=int,
        metavar="N",
        default=None,
        help="Nach Erfolg Messwertblock N einmal lesen und ausgeben",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="DEBUG-Logs (kw1281)")
    p.add_argument(
        "--no-local-echo",
        action="store_true",
        help="Kein separates Echo-Read nach TX (nur für manche Interfaces; Standard: Echo an)",
    )
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    log_path = args.log
    print(f"Port={args.port} baud={args.baud} attempts={args.attempts}", flush=True)
    print(f"Diagnose-Log: {log_path}", flush=True)

    ecu = KW1281(args.port, baud=args.baud, kkl_local_echo=not args.no_local_echo)
    try:
        ident = ecu.connect(
            ECU_ENGINE,
            max_attempts=args.attempts,
            diagnostic_log_path=log_path,
            between_attempts_s=args.between,
        )
        print(f"OK — Ident: {ident}", flush=True)

        if args.measure is not None:
            grp = ecu.read_measurement_block(args.measure)
            print(f"Messwertblock {grp.block_number}:", flush=True)
            if args.verbose:
                print(f"  Rohdaten (raw): {[hex(b) for b in grp.raw_data]}", flush=True)
            for label, value, unit in grp.values:
                print(f"  {label}: {value} {unit}", flush=True)

        return 0
    except KW1281Error as e:
        print(f"FEHLER: {e}", flush=True)
        return 1
    except KeyboardInterrupt:
        print("\nAbbruch (Ctrl+C)", flush=True)
        return 130
    finally:
        try:
            ecu.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
