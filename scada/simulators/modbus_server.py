"""
Modbus TCP Slave Simulator — Zone A sensors
============================================
Implements a minimal Modbus TCP server (Function Code 03: Read Holding
Registers) using raw sockets — no dependency on pymodbus server API.

Values are STATIC by default. The sensor console writes set-points to
Redis at  scada:setpoints  (HSET), and the updater thread reads them
every second so the register bank reflects the latest manual values.

Register layout (matching scada/config/register_map.yaml):
  40001 — temp_a     int16  scale=0.1   °C
  40002 — vib_a      int16  scale=0.01  g_rms
  40003 — gas_a      int16  scale=0.1   ppm
  40004 — noise_a    int16  scale=0.1   dB
  40005-40006 pressure_a  float32       bar
"""
import logging
import socket
import struct
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)
except ImportError:
    pass

import os
HOST = "0.0.0.0"

# ── Shared register banks (port-indexed, 0-based indices → addresses 40001+) ──
_SENSOR_PORTS = {
    "temp_a":     5021,
    "vib_a":      5022,
    "gas_a":      5023,
    "noise_a":    5024,
    "pressure_a": 5025,
}

_SENSOR_PORTS_REVERSE = {v: k for k, v in _SENSOR_PORTS.items()}

# 16 holding registers per simulator port to accommodate address offsets cleanly
_register_banks = {port: [0] * 16 for port in _SENSOR_PORTS.values()}
_lock = threading.Lock()

# Register map: sensor_id → (index, data_type, scale, offset)
_REG_MAP = {
    "temp_a":     (0, "int16",   0.1,  0.0),
    "vib_a":      (1, "int16",   0.01, 0.0),
    "gas_a":      (2, "int16",   0.1,  0.0),
    "noise_a":    (3, "int16",   0.1,  0.0),
    "pressure_a": (4, "float32", 1.0,  0.0),
}

# Default static values (no oscillation)
_DEFAULTS = {
    "temp_a":     28.0,
    "vib_a":      1.2,
    "gas_a":      1.5,
    "noise_a":    68.0,
    "pressure_a": 10.5,
}


def _encode(sensor_id: str, value: float) -> None:
    """Write engineering value into the correct port's register bank."""
    info = _REG_MAP.get(sensor_id)
    port = _SENSOR_PORTS.get(sensor_id)
    if not info or not port:
        return
    idx, dtype, scale, offset = info
    raw = (value - offset) / scale  # inverse of eng_value = raw*scale + offset
    regs = _register_banks[port]
    
    if dtype == "float32":
        fb = struct.pack(">f", value)   # float32 stores the eng value directly
        regs[idx]     = struct.unpack(">H", fb[0:2])[0]
        regs[idx + 1] = struct.unpack(">H", fb[2:4])[0]
    elif dtype == "int16":
        iv = int(round(raw))
        regs[idx] = iv & 0xFFFF
    else:
        regs[idx] = int(round(raw)) & 0xFFFF


def _updater() -> None:
    """
    Background thread: refreshes register banks from Redis setpoints every second.
    Falls back to static defaults if Redis is unavailable.
    """
    import redis as redis_lib

    r = None
    try:
        r = redis_lib.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
        )
        r.ping()
        log.info("[modbus-sim] Redis connected — setpoints key: scada:setpoints")
    except Exception as e:
        log.warning(f"[modbus-sim] Redis unavailable ({e}) — using static defaults")
        r = None

    # Only load defaults if Redis has no setpoints yet (avoids overwriting
    # manually-set values with simulator defaults on startup).
    if r:
        try:
            if not r.hlen("scada:setpoints"):
                with _lock:
                    for sid, val in _DEFAULTS.items():
                        _encode(sid, val)
        except Exception:
            with _lock:
                for sid, val in _DEFAULTS.items():
                    _encode(sid, val)
    else:
        with _lock:
            for sid, val in _DEFAULTS.items():
                _encode(sid, val)

    while True:
        if r:
            try:
                setpoints = r.hgetall("scada:setpoints")
                with _lock:
                    for sid, raw_str in setpoints.items():
                        if sid in _REG_MAP:
                            _encode(sid, float(raw_str))
            except Exception as e:
                log.warning(f"[modbus-sim] Redis read error: {e}")
        time.sleep(1)


# ── Modbus TCP handler ─────────────────────────────────────────────────────────

def _handle_client(conn: socket.socket, addr: tuple, port: int) -> None:
    log.info(f"Client connected on port {port}: {addr}")
    try:
        while True:
            header = b""
            while len(header) < 12:
                chunk = conn.recv(12 - len(header))
                if not chunk:
                    return
                header += chunk

            trans_id   = struct.unpack(">H", header[0:2])[0]
            func_code  = header[7]
            start_addr = struct.unpack(">H", header[8:10])[0]
            quantity   = struct.unpack(">H", header[10:12])[0]

            if func_code != 0x03:
                exc = struct.pack(">HHHBBB", trans_id, 0, 3, header[6], func_code | 0x80, 0x01)
                conn.sendall(exc)
                continue

            with _lock:
                regs = _register_banks[port]
                values = list(regs[start_addr: start_addr + quantity])
                values += [0] * max(0, quantity - len(values))

            byte_count  = quantity * 2
            mbap_length = 3 + byte_count
            response = struct.pack(
                f">HHHBBB{quantity}H",
                trans_id, 0, mbap_length, header[6], func_code, byte_count,
                *values,
            )
            conn.sendall(response)

    except (ConnectionResetError, BrokenPipeError, OSError):
        pass
    finally:
        conn.close()
        log.info(f"Client disconnected on port {port}: {addr}")


def _run_server(port: int) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, port))
    srv.listen(5)
    log.info(f"Modbus TCP slave on {HOST}:{port} serving {_SENSOR_PORTS_REVERSE.get(port)}")
    try:
        while True:
            conn, addr = srv.accept()
            t = threading.Thread(target=_handle_client, args=(conn, addr, port), daemon=True)
            t.start()
    except Exception as e:
        log.error(f"Server on port {port} failed: {e}")
    finally:
        srv.close()


def main() -> None:
    updater = threading.Thread(target=_updater, name="Updater", daemon=True)
    updater.start()

    # Start 5 independent listener threads, one per sensor port
    for port in _register_banks.keys():
        t = threading.Thread(target=_run_server, args=(port,), name=f"Server-{port}", daemon=True)
        t.start()

    log.info("Modbus TCP slave multi-port simulator started.")
    log.info("Ports: 5021=temp_a  5022=vib_a  5023=gas_a  5024=noise_a  5025=pressure_a")
    log.info("Setpoints: set via Redis HSET scada:setpoints <sensor_id> <value>")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Stopped.")


if __name__ == "__main__":
    main()
