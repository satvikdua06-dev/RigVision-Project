"""Publish a sample `ccm-matches` payload and print `3d-locations` output.

Run this while `cv/tracking/triangulation.py` is already running and
connected to the same Kafka broker.

Examples:
    python3 scripts/test_triangulation_kafka.py
    KAFKA_BOOTSTRAP_SERVERS=localhost:9092 python3 scripts/test_triangulation_kafka.py
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from typing import Any, Dict

from kafka import KafkaConsumer, KafkaProducer


SAMPLE_PAYLOAD: Dict[str, Any] = {
  "timestamp": 1717945618.123,
  "matched_persons": [
    {
      "track_id": 101,
      "posture": "standing",
      "recognition_method": "aruco",
      "frames_seen": 150,
      "frames_missing": 0,
      "per_camera": {
        "cam_0": {
          "bbox": [120.5, 200.0, 180.2, 450.5],
          "foot_point": [150.3, 450.5],
          "confidence": 0.92,
          "keypoints": [[150.0, 210.0], [148.0, 205.0], [152.0, 205.0]], 
          "aruco_id": 42,
          "aruco_confidence": 0.98,
          "features": None
        },
        "cam_1": {
          "bbox": [310.0, 210.0, 370.0, 460.0],
          "foot_point": [340.0, 460.0],
          "confidence": 0.89,
          "keypoints": [[340.0, 220.0], [338.0, 215.0], [342.0, 215.0]],
          "aruco_id": 42,
          "aruco_confidence": 0.95,
          "features": None
        }
      }
    },
    {
      "track_id": 102,
      "posture": "bending",
      "recognition_method": "reid_features",
      "frames_seen": 45,
      "frames_missing": 1,
      "per_camera": {
        "cam_0": {
          "bbox": [800.0, 300.0, 890.0, 480.0],
          "foot_point": [845.0, 480.0],
          "confidence": 0.85,
          "keypoints": [[845.0, 320.0], [840.0, 315.0], [850.0, 315.0]],
          "aruco_id": None,
          "aruco_confidence": 0.0,
          "features": [0.124, -0.453, 0.882, 0.019] 
        },
        "cam_2": {
          "bbox": [50.0, 400.0, 150.0, 580.0],
          "foot_point": [100.0, 580.0],
          "confidence": 0.78,
          "keypoints": [[100.0, 420.0], [95.0, 415.0], [105.0, 415.0]],
          "aruco_id": None,
          "aruco_confidence": 0.0,
          "features": [0.121, -0.450, 0.879, 0.022]
        }
      }
    }
  ]
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a sample triangulation message and print produced output.")
    parser.add_argument(
        "--bootstrap-servers",
        default=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        help="Kafka bootstrap servers, for example localhost:9092",
    )
    parser.add_argument("--input-topic", default=os.environ.get("IN_TOPIC", "ccm-matches"))
    parser.add_argument("--output-topic", default=os.environ.get("OUT_TOPIC", "3d-locations"))
    parser.add_argument("--timeout-seconds", type=int, default=15)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    producer = KafkaProducer(
        bootstrap_servers=[s.strip() for s in args.bootstrap_servers.split(",") if s.strip()],
        value_serializer=lambda payload: json.dumps(payload).encode("utf-8"),
    )

    consumer = KafkaConsumer(
        args.output_topic,
        bootstrap_servers=[s.strip() for s in args.bootstrap_servers.split(",") if s.strip()],
      group_id=f"triangulation-test-{uuid.uuid4().hex}",
      auto_offset_reset="latest",
        enable_auto_commit=True,
        consumer_timeout_ms=1000,
        value_deserializer=lambda message: json.loads(message.decode("utf-8")),
    )

    try:
        print(f"Connecting to {args.output_topic} and waiting for partition assignment...")
        consumer.poll(timeout_ms=100)
        while not consumer.assignment():
            time.sleep(0.1)
            consumer.poll(timeout_ms=100)
        print("Successfully connected and listening! \n")
        
        # 1. Send the dummy message to the input topic immediately
        print(f"Sending sample payload to {args.input_topic} on {args.bootstrap_servers}...")
        producer.send(args.input_topic, SAMPLE_PAYLOAD)
        producer.flush()

        # 2. Start waiting for the triangulation.py script to reply
        deadline = time.time() + args.timeout_seconds
        print(f"Waiting up to {args.timeout_seconds}s for output on {args.output_topic}...")

        seen_any = False
        while time.time() < deadline:
            records = consumer.poll(timeout_ms=1000)
            for _tp, messages in records.items():
                for message in messages:
                    seen_any = True
                    print("\n--- RECEIVED ENRICHED PAYLOAD FROM TRIANGULATION.PY ---")
                    print(json.dumps(message.value, indent=2, sort_keys=True))

            if seen_any:
                return 0

        print("No output received before timeout.")
        return 1
    
    finally:
        try:
            consumer.close()
        except Exception:
            pass
        try:
            producer.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
