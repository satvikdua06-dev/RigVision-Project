"""
Base classes shared by all SCADA protocol drivers.
"""
from __future__ import annotations

import queue
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class RawReading:
    """Protocol-agnostic raw reading before scaling/normalisation."""
    sensor_id: str
    raw_value: float
    protocol:  str          # "modbus" | "mqtt" | "hart" | "opcua"
    device:    str          # human label from config (e.g. "SIM-PLC-01")
    config:    dict         # register/topic config dict — carries scale, offset, unit


class PortWorker(threading.Thread, ABC):
    """
    One daemon thread, one host:port connection.
    Polls or subscribes forever; calls self.emit() per reading.
    Stopped via self._stop event (set by self.stop()).
    """

    def __init__(self, q: queue.Queue, config: dict):
        host = config.get("host", "local")
        port = config.get("port", 0)
        name = f"{self.__class__.__name__}@{host}:{port}"
        super().__init__(name=name, daemon=True)
        self.queue  = q
        self.config = config
        self._stop  = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def emit(self, raw: RawReading) -> None:
        try:
            self.queue.put_nowait(raw)
        except queue.Full:
            pass  # drop under backpressure — prefer dropping old data over blocking

    @abstractmethod
    def run(self) -> None: ...
