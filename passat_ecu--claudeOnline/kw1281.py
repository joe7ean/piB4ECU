"""
KW1281 Protocol Implementation for VW Passat B4 (1994)
KKL USB adapter on Raspberry Pi Zero 2W

KW1281 is a half-duplex, single-wire protocol over K-Line.
Each byte sent must be acknowledged by the ECU (complement ACK).
"""

import serial
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("kw1281")


# ── ECU addresses ──────────────────────────────────────────────────────────────
ECU_ENGINE     = 0x01   # Motorsteuergerät (Digifant / Motronic)
ECU_GEARBOX    = 0x02
ECU_ABS        = 0x03
ECU_DASH       = 0x17   # Kombiinstrument

# ── Block titles (KW1281 spec) ──────────────────────────────────────────────────
BLOCK_ACK         = 0x09
BLOCK_MEAS_VALUE  = 0x29   # Messwertblock response
BLOCK_MEAS_REQ    = 0xF7   # Messwertblock request
BLOCK_FAULT_REQ   = 0x07   # Fehlerspeicher lesen
BLOCK_FAULT_RESP  = 0xFC
BLOCK_FAULT_CLEAR = 0x05
BLOCK_END         = 0x06


@dataclass
class MeasurementGroup:
    """Decoded measurement group from a single ECU block response."""
    block_number: int
    values: list = field(default_factory=list)  # list of (label, value, unit)


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

    def __init__(self, port: str, baud: int = 9600, timeout: float = 2.0):
        self.port    = port
        self.baud    = baud
        self.timeout = timeout
        self.ser: Optional[serial.Serial] = None
        self.connected = False
        self._ecu_addr = None

    # ── Connection ─────────────────────────────────────────────────────────────

    def connect(self, ecu_addr: int = ECU_ENGINE) -> str:
        """
        5-baud slow init + KW1281 handshake.
        Returns ECU identification string.
        """
        self._ecu_addr = ecu_addr
        
        # WIR WISSEN JETZT: Das Steuergerät sendet mit 4800 Baud!
        baudrate = 4800
        log.info(f"Connecting to ECU 0x{ecu_addr:02X} on {self.port} at {baudrate} baud")

        # Open port for normal comms
        self.ser = serial.Serial(
            port=self.port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout
        )
        self.ser.close()

        # ── 5-baud init: send ECU address bit by bit ──────────────────────────
        self.ser.open()
        
        # WICHTIG: Vor der 5-Baud Init muss die K-Line für mind. 2 Sekunden HIGH sein (Idle)
        self.ser.break_condition = False
        time.sleep(2.5) # Etwas länger warten, um sicherzugehen
        
        # Start bit (LOW)
        self.ser.break_condition = True   
        time.sleep(0.2)                   # 200ms = 1 bit at 5 baud

        # LSB first
        for i in range(8):
            bit = (ecu_addr >> i) & 1
            self.ser.break_condition = not bool(bit)
            time.sleep(0.2)

        # Stop bit (HIGH)
        self.ser.break_condition = False  
        
        # WICHTIG: Empfangspuffer leeren, BEVOR wir die 200ms für das Stop-Bit warten!
        # Wenn das Steuergerät sehr schnell antwortet, sendet es das Sync-Byte vielleicht
        # schon während dieser 200ms. Wenn wir danach leeren, löschen wir das Sync-Byte.
        self.ser.reset_input_buffer()
        
        time.sleep(0.2)

        # ── Read sync byte 0x55, then KB1, KB2, then inverted addr ───────────
        sync = self._read_byte(timeout=3.0)
        
        if sync != 0x55:
            self.ser.close()
            raise KW1281Error(f"Kein Sync-Byte (got 0x{sync:02X}, expected 0x55)")

        kb1 = self._read_byte()
        kb2 = self._read_byte()
        log.debug(f"Sync: 0x55, KB1: 0x{kb1:02X}, KB2: 0x{kb2:02X}")

        # Echo inverted address
        self._send_byte(~ecu_addr & 0xFF)
        time.sleep(0.011)   # inter-byte gap

        # Read ECU identification blocks
        ident = self._read_identification()
        self.connected = True
        log.info(f"ECU ident: {ident}")
        return ident

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
            values=_decode_measurement_values(raw["data"])
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
        self.ser.write(bytes([byte & 0xFF]))
        self.ser.flush()
        
        # K-Line Adapter empfangen alles, was sie selbst senden (Lokales Echo).
        # Wir müssen dieses Echo auslesen und verwerfen, sonst stört es den nächsten Lesezugriff!
        echo = self.ser.read(1)
        if not echo:
            log.warning("Kein lokales Echo empfangen - Kabel defekt oder nicht eingesteckt?")

    def _read_byte(self, timeout: float = None) -> int:
        if timeout:
            self.ser.timeout = timeout
        data = self.ser.read(1)
        if not data:
            raise KW1281Error("Timeout beim Lesen — ECU antwortet nicht")
        self.ser.timeout = self.timeout
        return data[0]

    def _send_block(self, title: int, data: list[int]):
        """Send a KW1281 block: [length] [counter] [title] [data...] [end=0x03]"""
        length = len(data) + 3   # title + data + end byte
        block = [length, self._next_counter(), title] + data + [0x03]
        for byte in block:
            self._send_byte(byte)
            ack = self._read_byte()   # ECU echoes complement
            if ack != (~byte & 0xFF):
                log.warning(f"ACK mismatch: sent 0x{byte:02X}, got 0x{ack:02X}")
            time.sleep(0.001)

    def _receive_block(self) -> dict:
        """Read one KW1281 block from ECU, ACK each byte."""
        length = self._read_byte()
        self._send_byte(~length & 0xFF)
        time.sleep(0.001)

        counter = self._read_byte()
        self._send_byte(~counter & 0xFF)
        time.sleep(0.001)

        title = self._read_byte()
        self._send_byte(~title & 0xFF)
        time.sleep(0.001)

        data = []
        for _ in range(length - 3):
            b = self._read_byte()
            self._send_byte(~b & 0xFF)
            time.sleep(0.001)
            data.append(b)

        end = self._read_byte()   # 0x03
        self._send_byte(~end & 0xFF)

        return {"length": length, "counter": counter, "title": title, "data": data}

    def _read_identification(self) -> str:
        """Read ECU identification string from initial handshake blocks."""
        ident_parts = []
        while True:
            block = self._receive_block()
            if block["title"] == BLOCK_ACK:
                break
            # Title 0xF6 = ASCII identification data
            if block["title"] == 0xF6:
                text = "".join(chr(b) for b in block["data"] if 32 <= b < 127)
                ident_parts.append(text.strip())
            self._send_block(BLOCK_ACK, [])
        return " | ".join(ident_parts) or "Unbekannte ECU"

    _counter = 0
    def _next_counter(self) -> int:
        self._counter = (self._counter + 1) & 0xFF
        return self._counter

    def _assert_connected(self):
        if not self.connected:
            raise KW1281Error("Nicht verbunden — zuerst connect() aufrufen")


# ── Measurement value decoder ──────────────────────────────────────────────────

def _decode_measurement_values(data: list[int]) -> list[tuple]:
    """
    KW1281 measurement encoding: pairs of (type_byte, value_byte).
    Returns list of (label, value, unit).
    """
    results = []
    for i in range(0, len(data) - 1, 2):
        type_b  = data[i]
        value_b = data[i + 1]

        match type_b:
            case 0x01:  # RPM: value * 40
                results.append(("Drehzahl", value_b * 40, "U/min"))
            case 0x02:  # Temperatur: value - 40
                results.append(("Kühlmitteltemperatur", value_b - 40, "°C"))
            case 0x03:  # Spannung: value * 0.1
                results.append(("Spannung", round(value_b * 0.1, 1), "V"))
            case 0x04:  # Lambda: value * 0.005 + 0.5
                results.append(("Lambda", round(value_b * 0.005 + 0.5, 3), "λ"))
            case 0x05:  # Geschwindigkeit: value * 2
                results.append(("Geschwindigkeit", value_b * 2, "km/h"))
            case 0x06:  # Zündwinkel: (value - 128) * 0.75
                results.append(("Zündwinkel", round((value_b - 128) * 0.75, 1), "°KW"))
            case 0x07:  # Einspritzzeit: value * 0.1
                results.append(("Einspritzzeit", round(value_b * 0.1, 2), "ms"))
            case 0x08:  # Drosseklklappe: value * 0.4
                results.append(("Drosselklappe", round(value_b * 0.4, 1), "%"))
            case 0x0B:  # Luftmassenmesser: value * 0.01
                results.append(("Luftmasse", round(value_b * 0.01, 3), "g/s"))
            case 0x0F:  # Ansauglufttemperatur: value - 40
                results.append(("Ansauglufttemperatur", value_b - 40, "°C"))
            case _:
                results.append((f"Kanal_0x{type_b:02X}", value_b, "raw"))

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
