"""
RigVision-3D — Sensor Simulator
=================================

Publishes fake sensor data to Kafka topic `rigvision.sensors` for testing
without real IoT hardware. Uses sinusoidal patterns with Gaussian noise.

USAGE:
    python -m sensors.simulator.simulate
    python -m sensors.simulator.simulate --rate 2.0 --bootstrap-servers localhost:9092
"""

from __future__ import annotations

import json
import logging
import math
import os
import signal
import sys
import threading
import time
from typing import Optional

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sensor_sim")

shutdown_event = threading.Event()


def signal_handler(sig: int, frame: object) -> None:
    logger.info("Shutting down sensor simulator...")
    shutdown_event.set()

signal.signal(signal.SIGINT, signal_handler)

ZONES = ["zone_a", "corridor", "zone_b", "zone_a_f1", "corridor_f1", "zone_b_f1"]


def generate_reading(zone_id: str, t: float) -> dict:
    zone_offset = hash(zone_id) % 100 / 10.0

    temperature = 28.0 + 3.0 * math.sin(0.05 * t + zone_offset) + np.random.normal(0, 0.5)
    vibration = max(0.1, 1.5 + 0.5 * math.sin(0.1 * t + zone_offset) + np.random.normal(0, 0.2))
    noise = 70.0 + 5.0 * math.sin(0.08 * t + zone_offset) + np.random.normal(0, 2)
    gas_h2s = max(0.0, 1.0 + 0.5 * abs(math.sin(0.02 * t + zone_offset)) + np.random.normal(0, 0.3))
    pressure = 12.0 + 2.0 * math.sin(0.03 * t + zone_offset) + np.random.normal(0, 0.5)

    if zone_id == "zone_a" and int(t) % 60 > 50:
        temperature += 15.0

    return {
        "zone_id": zone_id,
        "temperature": round(float(temperature), 1),
        "vibration": round(float(vibration), 2),
        "noise": round(float(noise), 1),
        "gas_h2s": round(float(gas_h2s), 2),
        "pressure": round(float(pressure), 1),
        "timestamp": int(time.time() * 1000),
    }


def run_simulator(
    bootstrap_servers: str = "localhost:9092",
    topic: str = "rigvision.sensors",
    rate: float = 1.0,
) -> None:
    try:
        from kafka import KafkaProducer
    except ImportError:
        logger.error("kafka-python not installed. Run: pip install kafka-python")
        sys.exit(1)

    logger.info("Connecting to Kafka at %s, topic=%s", bootstrap_servers, topic)
    producer = KafkaProducer(
        bootstrap_servers=bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
    logger.info("Kafka producer connected. Publishing at %.1f Hz per zone...", rate)

    start_time = time.time()
    msg_count = 0

    while not shutdown_event.is_set():
        t = time.time() - start_time

        for zone_id in ZONES:
            reading = generate_reading(zone_id, t)
            producer.send(topic, value=reading)
            msg_count += 1

        if msg_count % (len(ZONES) * 10) == 0:
            logger.info("Published %d sensor readings", msg_count)

        sleep_time = max(0, (1.0 / rate) - (time.time() - start_time - t))
        if sleep_time > 0:
            shutdown_event.wait(timeout=sleep_time)

    producer.flush()
    producer.close()
    logger.info("Sensor simulator stopped after %d messages", msg_count)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="RigVision-3D Sensor Simulator")
    parser.add_argument("--bootstrap-servers", default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
    parser.add_argument("--topic", default=os.getenv("KAFKA_SENSOR_TOPIC", "rigvision.sensors"))
    parser.add_argument("--rate", type=float, default=1.0, help="Readings per second per zone (default: 1.0)")
    args = parser.parse_args()

    run_simulator(
        bootstrap_servers=args.bootstrap_servers,
        topic=args.topic,
        rate=args.rate,
    )


if __name__ == "__main__":
    main()
