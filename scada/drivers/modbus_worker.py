"""
Modbus TCP port worker — one thread per PLC/device.

Reads a contiguous block of holding registers each poll cycle, then
extracts individual sensor values by address offset.
Supports int16, uint16, and float32 (two consecutive registers, big-endian).

Config keys (from register_map.yaml):
  host, port, poll_interval_s, name
  registers[]:
    address      — Modbus address (40001-based, e.g. 40001)
    sensor_id    — must match zone_definitions.json
    data_type    — "int16" | "uint16" | "float32"
    scale        — eng_value = raw * scale + offset
    offset
    unit
"""
from __future__ import annotations

import logging
import struct
import time

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusException

from .base import PortWorker, RawReading

log = logging.getLogger(__name__)

_BACKOFF_MAX = 30


class ModbusPortWorker(PortWorker):

    def run(self) -> None:
        cfg         = self.config
        host        = cfg["host"]
        port        = int(cfg.get("port", 502))
        interval    = float(cfg.get("poll_interval_s", 1.0))
        registers   = cfg.get("registers", [])
        device_name = cfg.get("name", f"{host}:{port}")

        if not registers:
            log.warning(f"[modbus] {device_name} — no registers configured, exiting")
            return

        # Build a contiguous read plan: find min/max address, read one block
        addrs = [r["address"] for r in registers]
        min_addr = min(addrs)
        max_addr = max(addrs)

        # float32 occupies 2 registers, so extend block if last reg is float32
        last_reg = next((r for r in registers if r["address"] == max_addr), {})
        block_count = (max_addr - min_addr) + (2 if last_reg.get("data_type") == "float32" else 1)
        start_index = min_addr - 40001  # pymodbus uses 0-based HR index

        client  = ModbusTcpClient(host=host, port=port, timeout=3)
        backoff = 1

        while not self._stop.is_set():
            # ── Connect ───────────────────────────────────────────────────────
            if not client.is_socket_open():
                if not client.connect():
                    log.warning(f"[modbus] {device_name} — connect failed, retry in {backoff}s")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, _BACKOFF_MAX)
                    continue
                log.info(f"[modbus] {device_name} connected ({host}:{port})")
                backoff = 1

            # ── Read block ────────────────────────────────────────────────────
            try:
                result = client.read_holding_registers(start_index, count=block_count)
                if result.isError():
                    log.warning(f"[modbus] {device_name} — register read error: {result}")
                    client.close()
                    time.sleep(backoff)
                    backoff = min(backoff * 2, _BACKOFF_MAX)
                    continue
                backoff = 1
                regs = result.registers

                # ── Extract each sensor value ─────────────────────────────────
                for reg_cfg in registers:
                    idx = reg_cfg["address"] - min_addr   # offset within block
                    dtype = reg_cfg.get("data_type", "uint16")

                    if idx >= len(regs):
                        continue

                    try:
                        if dtype == "float32":
                            raw = struct.unpack(">f",
                                struct.pack(">HH", regs[idx], regs[idx + 1]))[0]
                        elif dtype == "int16":
                            raw = float(regs[idx] if regs[idx] < 32768 else regs[idx] - 65536)
                        else:  # uint16
                            raw = float(regs[idx])
                    except (struct.error, IndexError):
                        log.warning(f"[modbus] {reg_cfg['sensor_id']} — unpack failed")
                        continue

                    self.emit(RawReading(
                        sensor_id=reg_cfg["sensor_id"],
                        raw_value=raw,
                        protocol="modbus",
                        device=device_name,
                        config=reg_cfg,
                    ))

            except (ConnectionException, ModbusException) as e:
                log.warning(f"[modbus] {device_name} — read error: {e}")
                client.close()
                backoff = min(backoff * 2, _BACKOFF_MAX)

            time.sleep(interval)

        client.close()
        log.info(f"[modbus] {device_name} stopped")
