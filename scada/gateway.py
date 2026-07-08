"""
RigVision — SCADA Protocol Gateway
====================================
Entry point for the mini SCADA translation layer.

Architecture
------------
  Field devices  →  PortWorker threads  →  raw_queue
                                               ↓
                                        Normalizer thread  →  norm_queue
                                                                  ↓
                                                           Publisher thread
                                                          (Redis + TimescaleDB)

The main thread runs a **desired-state reconciler** every RECONCILE_INTERVAL
seconds:
  1. Read config files (desired state = {port_id: (WorkerClass, config)})
  2. Stop workers whose port was removed from config
  3. Start workers for newly-added ports
  4. Restart any crashed workers
  5. Restart the Publisher if it crashed

Hot-adding a new device: edit the relevant YAML config file — within
RECONCILE_INTERVAL seconds the gateway starts a new PortWorker thread
without any restart.

Run
---
  python -m scada.gateway            # from project root
  python scada/gateway.py            # direct
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from scada.drivers.base import PortWorker, RawReading
from scada.drivers.modbus_worker import ModbusPortWorker
from scada.drivers.mqtt_worker import MQTTWorker
from scada.drivers.hart_worker import HARTPortWorker
from scada.normalizer import normalize
from scada.publisher import Publisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("gateway")

RECONCILE_INTERVAL = int(os.getenv("SCADA_RECONCILE_INTERVAL", "5"))
_CONFIG_DIR = Path(__file__).parent / "config"


# ── Config loader ──────────────────────────────────────────────────────────────

def _load_yaml(filename: str) -> dict:
    path = _CONFIG_DIR / filename
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_desired() -> dict[str, tuple[type, dict]]:
    """
    Read all YAML config files and return the desired worker set as:
      { port_id_string: (WorkerClass, config_dict) }

    port_id is a stable key like "modbus:localhost:5020" — used to track
    whether a worker is already running.  Changing host/port in config
    creates a new key → stops old worker, starts new one automatically.
    """
    desired: dict[str, tuple[type, dict]] = {}

    # ── Modbus TCP devices ─────────────────────────────────────────────────────
    for name, cfg in (_load_yaml("register_map.yaml").get("devices") or {}).items():
        cfg = dict(cfg)
        cfg["name"] = name
        key = f"modbus:{cfg['host']}:{cfg.get('port', 502)}"
        desired[key] = (ModbusPortWorker, cfg)

    # ── HART-IP multiplexers ───────────────────────────────────────────────────
    for name, cfg in (_load_yaml("hart_devices.yaml").get("multiplexers") or {}).items():
        cfg = dict(cfg)
        cfg["name"] = name
        key = f"hart:{cfg['host']}:{cfg.get('port', 5094)}"
        desired[key] = (HARTPortWorker, cfg)

    # ── MQTT brokers ───────────────────────────────────────────────────────────
    for broker_cfg in (_load_yaml("mqtt_topics.yaml").get("brokers") or []):
        cfg = dict(broker_cfg)
        key = f"mqtt:{cfg['host']}:{cfg.get('port', 1883)}"
        desired[key] = (MQTTWorker, cfg)

    return desired


# ── Worker lifecycle ───────────────────────────────────────────────────────────

def _start_worker(cls: type, cfg: dict, q: queue.Queue) -> PortWorker:
    w = cls(q, cfg)
    w.daemon = True
    w.start()
    log.info(f"[gateway] >> started {w.name}")
    return w


# ── Normalizer bridge ──────────────────────────────────────────────────────────

def _normalizer_loop(raw_q: queue.Queue, norm_q: queue.Queue) -> None:
    """Bridge: drains raw_q, normalises, puts into norm_q."""
    while True:
        raw = raw_q.get()
        reading = normalize(raw)
        if reading is not None:
            try:
                norm_q.put_nowait(reading)
            except queue.Full:
                pass   # drop under backpressure
        raw_q.task_done()


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    raw_q  = queue.Queue(maxsize=10_000)
    norm_q = queue.Queue(maxsize=10_000)

    # Normalizer bridge (single thread — CPU cost is negligible)
    norm_thread = threading.Thread(
        target=_normalizer_loop, args=(raw_q, norm_q),
        name="Normalizer", daemon=True,
    )
    norm_thread.start()

    # Publisher (Redis + TimescaleDB)
    publisher = Publisher(norm_q)
    publisher.daemon = True
    publisher.start()

    workers: dict[str, PortWorker] = {}

    log.info(f"SCADA gateway starting - reconcile every {RECONCILE_INTERVAL}s")
    log.info(f"Config dir: {_CONFIG_DIR}")

    try:
        while True:
            desired = load_desired()

            # 1. Stop workers whose port was removed from config
            for key in list(workers):
                if key not in desired:
                    log.info(f"[gateway] -- stopping {key} (removed from config)")
                    workers.pop(key).stop()

            # 2. Start workers for ports not yet running
            for key, (cls, cfg) in desired.items():
                if key not in workers:
                    workers[key] = _start_worker(cls, cfg, raw_q)

            # 3. Restart crashed workers
            for key, (cls, cfg) in desired.items():
                if key in workers and not workers[key].is_alive():
                    log.warning(f"[gateway] ~~ restarting {key} (worker died)")
                    workers[key] = _start_worker(cls, cfg, raw_q)

            # 4. Restart publisher if it crashed
            if not publisher.is_alive():
                log.warning("[gateway] ~~ restarting Publisher")
                publisher = Publisher(norm_q)
                publisher.daemon = True
                publisher.start()

            # Status line
            alive = sum(1 for w in workers.values() if w.is_alive())
            log.info(f"[gateway] {alive}/{len(workers)} workers alive | "
                     f"raw_q={raw_q.qsize()} norm_q={norm_q.qsize()}")

            time.sleep(RECONCILE_INTERVAL)

    except KeyboardInterrupt:
        log.info("Shutting down...")
        for w in workers.values():
            w.stop()
        publisher.stop()
        log.info("Done.")


if __name__ == "__main__":
    main()
