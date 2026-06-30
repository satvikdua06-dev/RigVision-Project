from kafka import KafkaProducer
import json
import time

alert_payload = {
  "event_id": f"anom_{int(time.time())}",
  "zone_id": "room_2",
  "severity": "CRITICAL",
  "triggered_sensors": ["temperature", "vibration", "noise"],
  "telemetry_snapshot": {"temperature_c": 82.5, "vibration_mm_s": 2.1}
}

producer = KafkaProducer(
    bootstrap_servers=['localhost:9092'],
    value_serializer=lambda x: json.dumps(x).encode('utf-8')
)

print("Publishing alert to Kafka...")
producer.send('rigvision_alerts', alert_payload)
print("Simulated alert queued...")

time.sleep(0.5)

print("Alert successfully sent to Kafka broker!")

producer.flush()
producer.close()