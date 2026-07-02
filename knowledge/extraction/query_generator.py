import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class AnomalyQueryBuilder:
    """Parses anomaly payloads and constructs secure, parameterized Cypher queries."""
    
    @staticmethod
    def process_payload(json_payload: str) -> dict:
        """
        Parses the JSON and returns the necessary parameters for Neo4j.
        """
        try:
            data = json.loads(json_payload)
            zone_id = data.get("zone_id")
            triggered_sensors = data.get("triggered_sensors", [])
            
            if not zone_id:
                raise ValueError("Payload rejected: Missing 'zone_id'.")
            if not triggered_sensors:
                raise ValueError("Payload rejected: Missing 'triggered_sensors' array.")
                
            return {
                "zone_id": zone_id,
                "sensor_types": triggered_sensors
            }
        except json.JSONDecodeError as e:
            logging.error(f"Failed to decode incoming anomaly JSON: {e}")
            raise
            
    @staticmethod
    def get_cypher_template() -> str:
        """
        Returns the static Cypher query template utilizing $zone_id and $sensor_types.
        Matches the exact custom schema from Phase 1.
        """

        return """
        MATCH (z:Zone {id: $zone_id})-[:CONTAINS]->(d:Device)-[:CAN_EXPERIENCE]->(f:FailureMode)-[:INDICATED_BY]->(s:Symptom)
        MATCH (f)-[:REQUIRES_ACTION]->(a:Action)
        WHERE s.type IN $sensor_types
        RETURN d.name AS device_name,
               f.name AS suspected_failure,
               collect(DISTINCT s.condition) AS observed_symptoms,
               collect(DISTINCT a.name) AS required_actions
        """


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
    
    print("--- 1. Parsing Incoming Payload ---")
    query_parameters = builder.process_payload(mock_incoming_json)
    print(f"Extracted Parameters: {json.dumps(query_parameters, indent=2)}")
    
    print("\n--- 2. Generating Cypher Template ---")
    cypher_query = builder.get_cypher_template()
    print(cypher_query.strip())