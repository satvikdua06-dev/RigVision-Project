import paho.mqtt.client as mqtt
import json
import time

alert_payload = {
  "event_id": "anom_9b8c7d",
  "zone_id": "room_1",
  "severity": "CRITICAL",
  "triggered_sensors": ["temperature", "vibration", "noise"], 
  "telemetry_snapshot": {"temperature_c": 82.5, "vibration_mm_s": 2.1}
}

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.connect("localhost", 1883, 60)


client.loop_start()
client.publish("rigvision/alerts", json.dumps(alert_payload))
print("Simulated alert queued...")

time.sleep(0.5)

print("Alert successfully fired off to the broker!")

client.disconnect()
client.loop_stop()