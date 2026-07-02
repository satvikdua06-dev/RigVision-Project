"""RigVision-3D — Location Service (Kafka → Redis)

Final stage of the CV pipeline. Consumes triangulated persons from the Kafka topic
"3d-locations" (produced by tracking/triangulation.py), assigns each person to a zone,
fuses current sensor readings, and writes the real-time state to Redis:

    "3d-locations" ──► assign_zone + build_zone_states ──► rigvision:persons / rigvision:zones

Run order: pipeline.py (producer) → triangulation.py (triangulation) → this service.

Note: PPE is null for now (the new detector dropped PPE; the finetuned YOLO will add it
later). Persons without a 'position_3d' (single-camera / failed triangulation) are skipped.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time

import redis

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zone_state import load_zone_definitions, build_zone_states, read_sensor_readings, read_resolved_thresholds, assign_zone, DEFAULT_PPE

LOCATIONS_TOPIC = "3d-locations"
shutdown_event = False


def _handle(sig, frame):
    global shutdown_event
    shutdown_event = True


signal.signal(signal.SIGINT, _handle)
signal.signal(signal.SIGTERM, _handle)


def _cam_ids(per_camera: dict) -> list[int]:
    ids = []
    for k in per_camera.keys():
        try:
            ids.append(int(str(k).replace("cam_", "")))
        except ValueError:
            continue
    return sorted(ids)


def build_persons(matched_persons: list[dict], zone_defs: dict) -> list[dict]:
    persons = []
    for mp in matched_persons:
        pos = mp.get("position_3d")
        if pos is None:
            continue  # no 3D fix (single camera or rejected by reprojection) → skip
        x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
        zone = assign_zone((x, y, z), zone_defs)
        per_camera = mp.get("per_camera", {})
        confs = [c.get("confidence", 0.0) for c in per_camera.values()]
        persons.append({
            "id": int(mp.get("track_id", 0)),
            "x": round(x, 2), "y": round(y, 2), "z": round(z, 2),
            "zone": zone,
            "floor": 1 if (zone and zone.endswith("_f1")) else 0,
            "posture": mp.get("posture", "standing"),
            "ppe": dict(DEFAULT_PPE),  # PPE detection not yet integrated
            "confidence": round(float(max(confs)) if confs else 0.0, 2),
            "cameras_visible": len(per_camera),
            "camera_ids": _cam_ids(per_camera),
        })
    return persons


def main() -> None:
    from kafka import KafkaConsumer

    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_password = os.getenv("REDIS_PASSWORD") or None

    cv_dir = os.path.dirname(os.path.abspath(__file__))
    zone_defs = load_zone_definitions(os.path.join(os.path.dirname(cv_dir), "cad", "zone_definitions.json"))

    r = redis.Redis(host=redis_host, port=redis_port, password=redis_password, decode_responses=True)
    r.ping()

    consumer = KafkaConsumer(
        LOCATIONS_TOPIC,
        bootstrap_servers=[s.strip() for s in bootstrap.split(",") if s.strip()],
        group_id="rigvision-location-service",
        auto_offset_reset="latest",
        enable_auto_commit=True,
        value_deserializer=lambda v: v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else v,
        consumer_timeout_ms=1000,
    )

    print(f"[location] consuming '{LOCATIONS_TOPIC}' → Redis (rigvision:persons / rigvision:zones)")
    while not shutdown_event:
        try:
            for msg in consumer:
                if shutdown_event:
                    break
                try:
                    payload = json.loads(msg.value)
                except Exception:
                    continue
                persons = build_persons(payload.get("matched_persons", []), zone_defs)
                sensor_readings = read_sensor_readings(r)
                resolved_thresholds = read_resolved_thresholds(r)
                zone_states = build_zone_states(persons, sensor_readings, zone_defs, resolved_thresholds)
                try:
                    r.set("rigvision:persons", json.dumps(persons))
                    r.set("rigvision:zones", json.dumps(zone_states))
                except Exception as e:
                    print(f"[location] redis write error: {e}")
        except Exception as e:
            print(f"[location] loop error: {e}")
            time.sleep(0.5)

    consumer.close()
    print("[location] stopped")


if __name__ == "__main__":
    main()
