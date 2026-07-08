"""
RigVision-3D — Sensor Simulator (Per-Sensor Threads)
===================================================

Spawns a separate simulator thread for each sensor ID. Each thread publishes
individual sensor reading messages to the Kafka topic `rigvision.sensors`.

USAGE:
    python -m sensors.simulator.simulate
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

# 10 individual sensors across Zone A and Zone B
SENSORS = [
    "temp_a", "gas_a", "vib_a", "noise_a", "pressure_a",
    "temp_b", "gas_b", "vib_b", "noise_b", "pressure_b",
]


def generate_reading_value(sensor_id: str, t: float) -> float:
    sensor_offset = hash(sensor_id) % 100 / 10.0

    if "temp" in sensor_id:
        val = 28.0 + 3.0 * math.sin(0.05 * t + sensor_offset) + np.random.normal(0, 0.5)
        if sensor_id == "temp_a" and int(t) % 60 > 50:
            val += 15.0
        return round(float(val), 1)
    elif "vib" in sensor_id:
        val = max(0.1, 1.5 + 0.5 * math.sin(0.1 * t + sensor_offset) + np.random.normal(0, 0.2))
        return round(float(val), 2)
    elif "gas" in sensor_id:
        val = max(0.0, 1.0 + 0.5 * abs(math.sin(0.02 * t + sensor_offset)) + np.random.normal(0, 0.3))
        return round(float(val), 2)
    elif "noise" in sensor_id:
        val = 70.0 + 5.0 * math.sin(0.08 * t + sensor_offset) + np.random.normal(0, 2)
        return round(float(val), 1)
    elif "pressure" in sensor_id:
        val = 12.0 + 2.0 * math.sin(0.03 * t + sensor_offset) + np.random.normal(0, 0.5)
        return round(float(val), 1)

    return 0.0


def sensor_worker(sensor_id: str, producer, topic: str, rate: float) -> None:
    logger.info(f"Started worker thread for sensor: {sensor_id}")
    start_time = time.time()
    
    while not shutdown_event.is_set():
        t = time.time() - start_time
        val = generate_reading_value(sensor_id, t)
        
        payload = {
            "sensor_id": sensor_id,
            "value": val,
            "timestamp": int(time.time() * 1000),
        }
        
        try:
            producer.send(topic, value=payload)
        except Exception as e:
            logger.error(f"Error publishing {sensor_id}: {e}")
            
        sleep_time = max(0.1, 1.0 / rate)
        shutdown_event.wait(timeout=sleep_time)

    logger.info(f"Stopped worker thread for sensor: {sensor_id}")


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
    logger.info("Kafka producer connected. Spawning %d sensor threads at %.1f Hz...", len(SENSORS), rate)

    threads = []
    for sensor_id in SENSORS:
        t = threading.Thread(
            target=sensor_worker,
            args=(sensor_id, producer, topic, rate),
            name=f"Sim-{sensor_id}",
            daemon=True
        )
        t.start()
        threads.append(t)

    # Keep main thread alive to handle interruption signals
    while not shutdown_event.is_set():
        time.sleep(0.5)

    # Join threads (with timeout to prevent hanging on exit)
    for t in threads:
        t.join(timeout=1.0)
        
    producer.flush()
    producer.close()
    logger.info("Sensor simulator stopped.")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="RigVision-3D Multi-Threaded Sensor Simulator")
    parser.add_argument("--bootstrap-servers", default=os.getenv("KAFKA_BROKER_HOSTS", "localhost:9092"))
    parser.add_argument("--topic", default=os.getenv("KAFKA_SENSOR_TOPIC", "rigvision.sensors"))
    parser.add_argument("--rate", type=float, default=1.0, help="Updates per second per sensor (default: 1.0)")
    args = parser.parse_args()

    run_simulator(
        bootstrap_servers=args.bootstrap_servers,
        topic=args.topic,
        rate=args.rate,
    )


if __name__ == "__main__":
    main()
