"""
HART-IP port worker — one thread per HART multiplexer.

Sends HART CMD3 (read dynamic variables) over UDP to a HART-IP gateway
(port 5094).  Parses PV/SV/TV/QV floats and maps them to sensor IDs via
the hart_devices.yaml config.

Config keys (from hart_devices.yaml multiplexer entry):
  host, port (default 5094), poll_interval_s, name
  devices[]:
    address    — HART short address (0-15) on the multiplexer
    sensors:   — {pv: sensor_id, sv: sensor_id, ...}  (only mapped vars emitted)

Note: this implements raw HART framing over UDP.  Real HART-IP gateways
usually wrap this in a HART-IP session layer (RFC-like protocol from
FieldComm Group); adjust _build_cmd3 / _recv_frame if your gateway needs
the full HART-IP session token headers.
"""
from __future__ import annotations

import logging
import socket
import struct
import time

from .base import PortWorker, RawReading

log = logging.getLogger(__name__)

# Partial HART unit code → engineering unit string (HART spec Table 1)
_HART_UNITS: dict[int, str] = {
    0x20: "°C",   0x21: "°F",  0x22: "K",    0x23: "°R",
    0x07: "bar",  0x08: "psi", 0x09: "kPa",  0x0C: "Pa",
    0x26: "m³/h", 0x27: "L/h", 0x28: "mL/s",
    0x38: "g_rms", 0x39: "m/s²",
    0x1B: "dB",
    0x00: "",
}

_VAR_NAMES = ("pv", "sv", "tv", "qv")
_PREAMBLE   = b"\xff" * 5
_BACKOFF_MAX = 30


class HARTPortWorker(PortWorker):

    def run(self) -> None:
        cfg      = self.config
        host     = cfg["host"]
        port     = int(cfg.get("port", 5094))
        devices  = cfg.get("devices", [])
        interval = float(cfg.get("poll_interval_s", 2.0))
        mux_name = cfg.get("name", f"{host}:{port}")

        if not devices:
            log.warning(f"[hart] {mux_name} — no devices configured, exiting")
            return

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)
        backoff = 1

        log.info(f"[hart] {mux_name} polling {len(devices)} device(s)")

        while not self._stop.is_set():
            for dev_cfg in devices:
                if self._stop.is_set():
                    break
                addr       = int(dev_cfg.get("address", 0))
                sensor_map = dev_cfg.get("sensors", {})  # {pv: "temp_a", ...}

                frame = _build_cmd3(addr)
                try:
                    sock.sendto(frame, (host, port))
                    data, _ = sock.recvfrom(512)
                    readings = _parse_cmd3(data, sensor_map, mux_name)
                    for r in readings:
                        self.emit(r)
                    backoff = 1
                except socket.timeout:
                    log.warning(f"[hart] {mux_name} addr={addr} — timeout, retry in {backoff}s")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, _BACKOFF_MAX)
                except Exception as e:
                    log.warning(f"[hart] {mux_name} addr={addr} — {e}")

            time.sleep(interval)

        sock.close()
        log.info(f"[hart] {mux_name} stopped")


# ── Frame helpers ──────────────────────────────────────────────────────────────

def _build_cmd3(addr: int) -> bytes:
    """Build a HART CMD3 short-address request frame."""
    body = bytes([0x02, addr & 0x3F, 3, 0])  # start + short-addr + cmd3 + byte_count=0
    checksum = 0
    for b in body:
        checksum ^= b
    return _PREAMBLE + body + bytes([checksum])


def _parse_cmd3(data: bytes, sensor_map: dict, device: str) -> list[RawReading]:
    """
    Parse a CMD3 response and return one RawReading per mapped variable.
    CMD3 data layout (after status bytes):
      [unit_code:1][value:4] × 4   (PV, SV, TV, QV)
    """
    readings: list[RawReading] = []
    try:
        # Skip preamble bytes (0xFF)
        i = 0
        while i < len(data) and data[i] == 0xFF:
            i += 1
        if i >= len(data):
            return readings
        i += 1          # start delimiter
        i += 1          # address (short format = 1 byte)
        i += 1          # command echo
        byte_count = data[i]; i += 1
        i += 2          # response code + field device status

        for var in _VAR_NAMES:
            if i + 5 > len(data):
                break
            unit_code = data[i]; i += 1
            value = struct.unpack(">f", data[i: i + 4])[0]; i += 4
            unit  = _HART_UNITS.get(unit_code, "")
            sid   = sensor_map.get(var)
            if sid:
                readings.append(RawReading(
                    sensor_id=sid,
                    raw_value=value,
                    protocol="hart",
                    device=device,
                    config={"scale": 1.0, "offset": 0.0, "unit": unit},
                ))
    except (IndexError, struct.error):
        pass
    return readings
