"""
KW1281 Protocol Implementation for VW Passat B4 (1994)
KKL USB adapter on Raspberry Pi Zero 2W

KW1281 is a half-duplex, single-wire protocol over K-Line.
Each byte sent must be acknowledged by the ECU (complement ACK).
"""

import json
import serial
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("kw1281")


# ── ECU addresses ──────────────────────────────────────────────────────────────
ECU_ENGINE     = 0x01   # Motorsteuergerät (Digifant / Motronic)
ECU_GEARBOX    = 0x02
ECU_ABS        = 0x03
ECU_DASH       = 0x17   # Kombiinstrument

# ── Block titles (KW1281 spec) ──────────────────────────────────────────────────
BLOCK_ACK         = 0x09
# Messwert/GroupRead Antwort (bei vielen VW-KWP/KW1281 Implementierungen).
# kw1281test verwendet dafür BlockTitle.GroupReadResponse = 0xE7.
BLOCK_MEAS_VALUE  = 0xE7

# Request-Titel: Measuring values / GroupRead wird über 0x29 angefordert.
BLOCK_MEAS_REQ    = 0x29   # Messwertblock request
BLOCK_FAULT_REQ   = 0x07   # Fehlerspeicher lesen
BLOCK_FAULT_RESP  = 0xFC
BLOCK_FAULT_CLEAR = 0x05
BLOCK_END         = 0x06


@dataclass
class MeasurementGroup:
    """Decoded measurement group from a single ECU block response."""
    block_number: int
    values: list = field(default_factory=list)  # list of (label, value, unit)
    raw_data: list[int] = field(default_factory=list)  # raw KW1281 payload bytes


@dataclass
class FaultCode:
    code: int
    description: str
    status: str   # "gespeichert" | "sporadisch"


class KW1281Error(Exception):
    pass


class KW1281:
    """
    Low-level KW1281 driver.

    Usage:
        ecu = KW1281('/dev/ttyUSB0')
        ecu.connect(ECU_ENGINE)
        data = ecu.read_block(1)
        ecu.disconnect()
    """

    def __init__(
        self,
        port: str,
        baud: int = 4800,
        timeout: float = 2.0,
        *,
        kkl_local_echo: bool = True,
    ):
        self.port    = port
        self.baud    = baud
        self.timeout = timeout
        self._kkl_local_echo = kkl_local_echo
        self.ser: Optional[serial.Serial] = None
        self.connected = False
        self._ecu_addr = None

    # ── Connection ─────────────────────────────────────────────────────────────

    def connect(
        self,
        ecu_addr: int = ECU_ENGINE,
        *,
        max_attempts: int = 1,
        diagnostic_log_path: Optional[str] = None,
        between_attempts_s: float = 2.0,
    ) -> str:
        """
        5-baud slow init + KW1281 handshake.
        Returns ECU identification string.

        Optional: repeat up to `max_attempts` times (K-Line idle between tries).
        If `diagnostic_log_path` is set, each attempt is appended as one JSON line
        for later analysis (sync hunt vs. KB2/ident).
        """
        self._ecu_addr = ecu_addr
        run_id = datetime.now(timezone.utc).isoformat()
        last_error: Optional[KW1281Error] = None

        for attempt in range(1, max_attempts + 1):
            record: dict[str, Any] = {
                "run_id": run_id,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "port": self.port,
                "baud": self.baud,
                "ecu_addr_hex": f"0x{ecu_addr:02X}",
                "timeout_s": self.timeout,
                "idle_before_init_s": 2.5,
            }
            try:
                ident = self._connect_once(ecu_addr, record)
                record["success"] = True
                record["ident_snippet"] = (ident[:120] + "…") if len(ident) > 120 else ident
                self._append_diagnostic_line(diagnostic_log_path, record)
                log.info(f"ECU ident: {ident}")
                return ident
            except KW1281Error as e:
                last_error = e
                record["success"] = False
                record["error"] = str(e)
                self._append_diagnostic_line(diagnostic_log_path, record)
                log.warning(
                    "ECU connect attempt %s/%s failed: %s (phase=%s)",
                    attempt,
                    max_attempts,
                    e,
                    record.get("phase"),
                )
            finally:
                if not self.connected and self.ser:
                    try:
                        self.ser.close()
                    except Exception:
                        pass
                    self.ser = None

            if attempt < max_attempts:
                time.sleep(between_attempts_s)

        msg = f"{last_error} (nach {max_attempts} Versuchen)"
        if diagnostic_log_path:
            msg += f"; Diagnose: {diagnostic_log_path}"
        raise KW1281Error(msg)

    def _append_diagnostic_line(self, path: Optional[str], record: dict[str, Any]) -> None:
        if not path:
            return
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _connect_once(self, ecu_addr: int, record: dict[str, Any]) -> str:
        """Single open → handshake → ident; closes port on failure; leaves open on success."""
        self.connected = False
        baudrate = self.baud
        log.info(
            "Connecting to ECU %s on %s at %s baud (attempt %s)",
            record["ecu_addr_hex"],
            self.port,
            baudrate,
            record.get("attempt"),
        )

        record["phase"] = "open_serial"
        self.ser = serial.Serial(
            port=self.port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
        )
        self.ser.close()
        self.ser.open()

        try:
            idle = float(record.get("idle_before_init_s", 2.5))
            record["phase"] = "kline_idle"
            self.ser.break_condition = False
            time.sleep(idle)

            record["phase"] = "pre_5baud_buffer_clear"
            self.ser.reset_input_buffer()

            record["phase"] = "5baud_init"
            self.ser.break_condition = True
            time.sleep(0.2)
            for i in range(8):
                bit = (ecu_addr >> i) & 1
                self.ser.break_condition = not bool(bit)
                time.sleep(0.2)
            self.ser.break_condition = False
            time.sleep(0.2)

            record["phase"] = "sync_hunt"
            record["pre_sync_garbage_hex"] = []
            record["pre_sync_zero_count"] = 0
            sync = None
            t0 = time.time()
            while time.time() - t0 < 3.0:
                self.ser.timeout = 0.5
                data = self.ser.read(1)
                if data:
                    b = data[0]
                    if b == 0x55:
                        sync = b
                        break
                    if b == 0x00:
                        record["pre_sync_zero_count"] = record.get("pre_sync_zero_count", 0) + 1
                    else:
                        garb = record["pre_sync_garbage_hex"]
                        if len(garb) < 48:
                            garb.append(f"0x{b:02X}")
                    log.debug("Unerwartetes Byte vor Sync: 0x%02X", b)

            record["sync_hunt_duration_ms"] = round((time.time() - t0) * 1000.0, 1)
            self.ser.timeout = self.timeout

            if sync != 0x55:
                record["phase"] = "sync_timeout"
                record["sync_ok"] = False
                raise KW1281Error("Kein Sync-Byte 0x55 gefunden (Timeout beim Lesen)")

            record["sync_ok"] = True
            record["phase"] = "read_kb1"

            kb1 = self._read_byte()
            record["kb1_hex"] = f"0x{kb1:02X}"
            record["phase"] = "read_kb2"

            kb2 = self._read_byte()
            record["kb2_hex"] = f"0x{kb2:02X}"
            record["phase"] = "kb2_received"
            log.debug("Sync: 0x55, KB1: 0x%02X, KB2: 0x%02X", kb1, kb2)

            complement = (~kb2) & 0xFF
            record["complement_sent_hex"] = f"0x{complement:02X}"
            record["phase"] = "send_kb2_complement"
            # kw1281test KwpCommon: 25 ms vor Komplement von Keyword-MSB (KB2)
            time.sleep(0.025)

            self.ser.write(bytes([complement]))
            self.ser.flush()

            echo_b = self.ser.read(1)
            if echo_b:
                record["echo_after_complement_hex"] = f"0x{echo_b[0]:02X}"
                if echo_b[0] != complement:
                    record["echo_mismatch"] = True
                else:
                    record["echo_mismatch"] = False
            else:
                record["echo_after_complement_hex"] = None
                record["echo_mismatch"] = None

            record["phase"] = "read_identification"
            ident = self._read_identification()
            record["phase"] = "success"
            self.connected = True
            return ident
        except KW1281Error:
            raise
        except Exception as e:
            record["phase"] = record.get("phase", "unknown")
            record["unexpected_exc"] = repr(e)
            raise KW1281Error(f"Handshake-Fehler: {e}") from e
        finally:
            if not self.connected and self.ser:
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None

    def disconnect(self):
        if self.ser and self.connected:
            try:
                self._send_block(BLOCK_END, [])
            except Exception:
                pass
        if self.ser:
            self.ser.close()
        self.connected = False

    # ── Public API ─────────────────────────────────────────────────────────────

    def read_measurement_block(self, block_number: int) -> MeasurementGroup:
        """Request and decode a measurement block (1–255)."""
        self._assert_connected()
        self._send_block(BLOCK_MEAS_REQ, [block_number])
        raw = self._receive_block()

        if raw["title"] != BLOCK_MEAS_VALUE:
            raise KW1281Error(f"Unerwarteter Block-Typ 0x{raw['title']:02X}")

        return MeasurementGroup(
            block_number=block_number,
            values=_decode_measurement_values(raw["data"], block_number=block_number),
            raw_data=raw["data"],
        )

    def read_fault_codes(self) -> list[FaultCode]:
        """Read stored fault codes from ECU."""
        self._assert_connected()
        self._send_block(BLOCK_FAULT_REQ, [])
        faults = []

        while True:
            raw = self._receive_block()
            if raw["title"] == BLOCK_ACK:
                break
            if raw["title"] == BLOCK_FAULT_RESP and len(raw["data"]) >= 3:
                code = (raw["data"][0] << 8) | raw["data"][1]
                status_byte = raw["data"][2]
                faults.append(FaultCode(
                    code=code,
                    description=_dtc_description(code),
                    status="sporadisch" if status_byte & 0x01 else "gespeichert"
                ))

        return faults

    def clear_fault_codes(self):
        """Clear all stored fault codes."""
        self._assert_connected()
        self._send_block(BLOCK_FAULT_CLEAR, [])
        self._receive_block()  # ACK

    # ── Low-level I/O ──────────────────────────────────────────────────────────

    def _send_byte(self, byte: int):
        """TX + ggf. ein lokales Echo lesen (KKL). Kein zweites Read — das würde das
        nächste ECU-Byte bei ReadAndAck schlucken und Timeouts erzeugen."""
        b = byte & 0xFF
        self.ser.write(bytes([b]))
        self.ser.flush()
        if not self._kkl_local_echo:
            return
        time.sleep(0.002)
        echo = self.ser.read(1)
        if not echo:
            log.debug("Kein lokales Echo empfangen.")
        elif echo[0] != b:
            log.debug("Lokales Echo fehlerhaft: sent 0x%02X, echo 0x%02X", b, echo[0])

    def _read_and_ack_ecu_byte(self) -> int:
        """ECU-Byte lesen, kurze Pause (R6), Komplement senden (nur Echo verwerfen)."""
        b = self._read_byte()
        time.sleep(0.002)
        self._send_byte(~b & 0xFF)
        return b

    def _read_block_first_length_with_resync(self, depth: int = 0) -> int:
        """
        Erstes Byte eines empfangenen Blocks (Länge); bei 0x55 erneuter Mini-Handshake
        wie kw1281test ReadAndAckByteFirst.
        """
        if depth > 5:
            raise KW1281Error("Blockanfang: zu oft Sync 0x55 — Synchronisation fehlgeschlagen")
        b = self._read_byte()
        if b == 0x55:
            log.warning("Sync 0x55 innerhalb Block — KB1/KB2 erneut, Komplement")
            kb1 = self._read_byte()
            kb2 = self._read_byte()
            time.sleep(0.025)
            comp = (~kb2) & 0xFF
            self.ser.write(bytes([comp]))
            self.ser.flush()
            if self._kkl_local_echo:
                echo = self.ser.read(1)
                if echo and echo[0] != comp:
                    log.debug("Echo nach Resync-Komplement: 0x%02X", echo[0])
            return self._read_block_first_length_with_resync(depth + 1)
        time.sleep(0.002)
        self._send_byte(~b & 0xFF)
        return b

    def _read_byte(self, timeout: float = None) -> int:
        if timeout:
            self.ser.timeout = timeout
        
        # Wir lesen 1 Byte. Wenn der Puffer leer ist, blockiert read() bis zum Timeout.
        data = self.ser.read(1)
        
        # Reset timeout to default
        self.ser.timeout = self.timeout
        
        if not data:
            raise KW1281Error("Timeout beim Lesen — ECU antwortet nicht")
            
        return data[0]

    def _send_block(self, title: int, data: list[int]):
        """Send a KW1281 block: [length] [counter] [title] [data...] [end=0x03]"""
        time.sleep(0.025)
        length = len(data) + 3   # title + data + end byte
        block = [length, self._next_counter(), title] + data + [0x03]
        for i, byte in enumerate(block):
            self._send_byte(byte)
            # Block-Ende 0x03 wird laut Protokoll / kw1281test NICHT mit ECU-Complement beantwortet
            if i == len(block) - 1 and byte == 0x03:
                break
            ack = self._read_byte()
            if ack != (~byte & 0xFF):
                log.debug(f"ACK mismatch (ignoriert): sent 0x{byte:02X}, got 0x{ack:02X}")
            time.sleep(0.002)

    def _receive_block(self) -> dict:
        """Read one KW1281 block from ECU, ACK each byte."""
        length = self._read_block_first_length_with_resync()
        counter = self._read_and_ack_ecu_byte()
        # KW1281: Der Block-Count ist synchronisierungsrelevant.
        # Nach dem Empfang müssen wir unseren Counter auf den empfangenen Wert setzen,
        # damit spätere ACK-Blöcke korrekt aufbauen (wie bei kw1281test).
        self._counter = counter
        title = self._read_and_ack_ecu_byte()
        data = []
        for _ in range(length - 3):
            data.append(self._read_and_ack_ecu_byte())
        end = self._read_byte()
        if end != 0x03:
            log.debug("Block-Ende erwartet 0x03, got 0x%02X", end)

        return {"length": length, "counter": counter, "title": title, "data": data}

    def _read_identification(self) -> str:
        """Read ECU identification string from initial handshake blocks."""
        ident_parts = []
        last_titles: list[int] = []
        for _ in range(48):
            block = self._receive_block()
            last_titles.append(block.get("title", -1))
            if block["title"] == BLOCK_ACK:
                break
            # Title 0xF6 = ASCII identification data
            if block["title"] == 0xF6:
                text = "".join(chr(b) for b in block["data"] if 32 <= b < 127)
                ident_parts.append(text.strip())
            self._send_block(BLOCK_ACK, [])
        else:
            # Hilft beim Debugging: zeigt, was wir zuletzt statt 0x09 bekommen haben.
            suffix = ", ".join(f"0x{t:02X}" for t in last_titles[-10:] if isinstance(t, int) and t >= 0)
            raise KW1281Error(
                "Identifikation: kein Abschlussblock (0x09) — Abbruch nach 48 Segmenten; "
                f"zuletzt: [{suffix}]"
            )
        return " | ".join(ident_parts) or "Unbekannte ECU"

    _counter = 0
    def _next_counter(self) -> int:
        self._counter = (self._counter + 1) & 0xFF
        return self._counter

    def _assert_connected(self):
        if not self.connected:
            raise KW1281Error("Nicht verbunden — zuerst connect() aufrufen")


# ── Measurement value decoder ──────────────────────────────────────────────────

def _decode_measurement_values(data: list[int], *, block_number: int) -> list[tuple]:
    """
    KW1281/KWP1281 measurement encoding (Blocktitle 0xE7):
    The payload is encoded as triplets: (meaning_byte, a_byte, b_byte).

    For your VW Passat B4 1.8l Mono-Motronic, the meaning_byte maps to:
      - 0x01: RPM
      - 0x05: temperature (coolant for block 1, EGR temp for block 2)
      - 0x0B: lambda correction factor
      - 0x10: operating status bitmask
      - 0x0F: injection timing (ms) (block 2)
      - 0x06: voltage supply (V) (block 2)

    Note: exact scaling can be ECU-specific; current formulas are aligned to your live tests.
    Returns list of (label, value, unit).
    """
    results = []
    for i in range(0, len(data) - 2, 3):
        meaning = data[i]
        a = data[i + 1]
        b = data[i + 2]

        match meaning:
            case 0x01:  # RPM
                # KWP1281-Formel (E7 meaning 0x01): a * 0.2 * b
                # Trifft deine Referenzen sauber:
                # - Motor aus: b=0   -> 0 RPM
                # - Idle:      b=37  -> 925 RPM (~920)
                # - 2000 RPM:  b=80  -> 2000 RPM
                rpm = int(round(a * 0.2 * b))
                results.append(("Drehzahl", rpm, "U/min"))

            case 0x05:  # temperature
                # 0.1*a*b - 10*a  (°C)
                temp_c = 0.1 * a * b - 10 * a
                if block_number == 1:
                    results.append(("Kühlmitteltemperatur", round(temp_c, 1), "°C"))
                else:
                    results.append(("Abgasrückführung", round(temp_c, 1), "°C"))

            case 0x0B:  # lambda correction factor
                # 0.0001*a*(b-128)+1
                lam = 0.0001 * a * (b - 128) + 1
                results.append(("Lambda", round(lam, 3), "λ"))

            case 0x10:  # operating status bitmask
                # In deinen Rohdaten ist die Nutz-Byte der Statusmask 'b' (z.B. 0x42 => 01000010)
                results.append(("Betriebszustand", b, "bit"))

            case 0x0F:  # injection timing (ms) (block 2)
                inj_ms = 0.01 * a * b
                results.append(("Einspritzzeit", round(inj_ms, 2), "ms"))

            case 0x06:  # voltage supply (V)
                volt = 0.001 * a * b
                results.append(("Spannung", round(volt, 1), "V"))

            case _:
                results.append((f"Kanal_0x{meaning:02X}", b, "raw"))

    return results


# ── DTC lookup table (VW-spezifisch) ──────────────────────────────────────────

_DTC_TABLE = {
    0x0130: "Lambdasonde — Signal außerhalb Bereich",
    0x0115: "Kühlmitteltemperatur-Sensor — Fehler",
    0x0102: "Luftmassenmesser — Unterbrechung",
    0x0104: "Drosselklappensensor — Kurzschluss",
    0x0506: "Leerlaufregelung — Abweichung",
    0x0540: "Klopfsensor — Fehler",
    0x1105: "Zündspule Zyl. 1 — Unterbrechung",
    0x1106: "Zündspule Zyl. 2 — Unterbrechung",
    0x1107: "Zündspule Zyl. 3 — Unterbrechung",
    0x1108: "Zündspule Zyl. 4 — Unterbrechung",
}

def _dtc_description(code: int) -> str:
    return _DTC_TABLE.get(code, f"Unbekannter Fehler (0x{code:04X})")
