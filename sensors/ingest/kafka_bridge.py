from __future__ import annotations
import json, logging, os, signal, sys, threading, time
from typing import Dict, Optional
import redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("kafka_bridge")
shutdown_event = threading.Event()

def signal_handler(sig, frame):
    shutdown_event.set()

signal.signal(signal.SIGINT, signal_handler)

SF = ("temperature", "vibration", "noise", "gas_h2s", "pressure")
TH = {
    "temperature": {"warning": 45.0, "critical": 70.0},
    "vibration":   {"warning": 3.0,  "critical": 5.0},
    "noise":       {"warning": 85.0, "critical": 100.0},
    "gas_h2s":     {"warning": 10.0, "critical": 20.0},
    "pressure":    {"warning": 18.0, "critical": 22.0},
}

def determine_sensor_status(readings: dict[str, float]) -> tuple[str, Optional[str]]:
    status, reason = "normal", None
    for k, v in readings.items():
        if k in TH:
            t = TH[k]
            if v >= t["critical"]: return "critical", f"{k} = {v:.1f} exceeds critical ({t['critical']})"
            if v >= t["warning"] and status != "critical":
                status, reason = "warning", f"{k} = {v:.1f} exceeds warning ({t['warning']})"
    return status, reason

def run_bridge(bootstrap_servers="localhost:9092", topic="rigvision.sensors", redis_host="localhost", redis_port=6379, redis_password=None, consumer_group="rigvision-bridge") -> None:
    try:
        from kafka import KafkaConsumer
    except ImportError:
        logger.error("pip install kafka-python")
        sys.exit(1)

    r_client = redis.Redis(host=redis_host, port=redis_port, password=redis_password or os.getenv("REDIS_PASSWORD"), decode_responses=True)
    r_client.ping()
    consumer = KafkaConsumer(topic, bootstrap_servers=bootstrap_servers, group_id=consumer_group, auto_offset_reset="latest", value_deserializer=lambda m: json.loads(m.decode("utf-8")), consumer_timeout_ms=1000)
    logger.info("Kafka consumer connected")

    msg_count = 0
    while not shutdown_event.is_set():
        try:
            records = consumer.poll(timeout_ms=500)
            for tp, messages in records.items():
                for msg in messages:
                    try:
                        data = msg.value
                        zone_id = data.get("zone_id")
                        if not zone_id: continue
                        readings = {f: float(data[f]) for f in SF if f in data}
                        if not readings: continue

                        zones_raw = r_client.get("rigvision:zones")
                        zones = json.loads(zones_raw) if zones_raw else {}
                        state = zones.get(zone_id, {
                            "status": "normal", "warning_reason": None,
                            "temperature": 28.0, "vibration": 1.2, "noise": 72.0, "gas_h2s": 0.5, "pressure": 12.0,
                            "person_count": 0, "ppe_violations": [], "updated_at": int(time.time()),
                        })
                        for f, v in readings.items(): state[f] = round(v, 2)
                        status, reason = determine_sensor_status({f: state.get(f, 0) for f in SF})

                        if state.get("ppe_violations") and status != "critical":
                            state["status"], state["warning_reason"] = "warning", reason
                        else:
                            state["status"], state["warning_reason"] = status, reason

                        state["updated_at"] = int(time.time())
                        zones[zone_id] = state
                        r_client.set("rigvision:zones", json.dumps(zones))
                        msg_count += 1
                    except Exception as e:
                        logger.warning("Failed to process message: %s", e)
        except Exception as e:
            logger.error("Poll error: %s", e)
            time.sleep(2)
    consumer.close()

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Kafka-to-Redis Sensor Bridge")
    parser.add_argument("--bootstrap-servers", default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
    parser.add_argument("--topic", default=os.getenv("KAFKA_SENSOR_TOPIC", "rigvision.sensors"))
    parser.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "localhost"))
    parser.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", "6379")))
    parser.add_argument("--redis-password", default=None)
    args = parser.parse_args()
    run_bridge(bootstrap_servers=args.bootstrap_servers, topic=args.topic, redis_host=args.redis_host, redis_port=args.redis_port, redis_password=args.redis_password)

if __name__ == "__main__":
    main()
