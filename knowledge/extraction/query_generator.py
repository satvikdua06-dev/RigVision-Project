import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class AnomalyQueryBuilder:
    """Parses and validates incoming anomaly payloads into Neo4j query params."""
    
    @staticmethod
    def process_payload(json_payload: str) -> dict:
        """
        Parses the JSON and returns the necessary parameters for Neo4j.
        """
        try:
            data = json.loads(json_payload)
            zone_id = data.get("zone_id")
            triggered_sensors = data.get("triggered_sensors", [])
            threshold_context = data.get("threshold_context") or {}

            if not zone_id:
                raise ValueError("Payload rejected: Missing 'zone_id'.")
            if not triggered_sensors:
                raise ValueError("Payload rejected: Missing 'triggered_sensors' array.")

            # Direction-qualify the KG symptom tokens: a sensor breached on its LOW
            # side maps to the "<type>_low" symptom (e.g. pressure_low) so the graph
            # returns the loss-of-pressure failure modes rather than the overpressure
            # ones. High-side (or unknown) breaches use the base type unchanged.
            sensor_types = []
            for t in triggered_sensors:
                direction = (threshold_context.get(t) or {}).get("breach_direction", "high")
                sensor_types.append(f"{t}_low" if direction == "low" else t)

            return {
                "zone_id": zone_id,
                "sensor_types": sensor_types
            }
        except json.JSONDecodeError as e:
            logging.error(f"Failed to decode incoming anomaly JSON: {e}")
            raise


if __name__ == "__main__":
    mock_incoming_json = '''
    {
      "event_id": "anom_9b8c7d",
      "timestamp": "2026-06-01T12:15:30Z",
      "zone_id": "room_1",
      "severity": "CRITICAL",
      "triggered_sensors": [
        "temperature",
        "vibration"
      ],
      "telemetry_snapshot": {
        "temperature_c": 82.5,
        "vibration_mm_s": 12.4
      }
    }
    '''
    
    builder = AnomalyQueryBuilder()
    
    print("--- Parsing Incoming Payload ---")
    query_parameters = builder.process_payload(mock_incoming_json)
    print(f"Extracted Parameters: {json.dumps(query_parameters, indent=2)}")