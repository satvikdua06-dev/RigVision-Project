import json
import logging
import os
from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SubgraphExtractor:
    def __init__(self):
        """
        Initializes the Neo4j driver connection by reading credentials
        from environment variables.
        """
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "rigvision_neo4j")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        """Closes the database connection cleanly."""
        self.driver.close()

    # Device failures: suspects are equipment in the zone whose failure modes are
    # indicated by at least one triggered sensor type; fetch the FULL expected
    # symptom profile + required actions for each suspect.
    DEVICE_QUERY = """
    MATCH (z:Zone {id: $zone_id})-[:CONTAINS]->(d:Device)
          -[:CAN_EXPERIENCE]->(f:FailureMode)-[:INDICATED_BY]->(trigger_s:Symptom)
    WHERE trigger_s.type IN $sensor_types
    MATCH (f)-[:INDICATED_BY]->(all_s:Symptom)
    MATCH (f)-[:REQUIRES_ACTION]->(a:Action)
    RETURN DISTINCT d.name AS device,
           d.model AS model,
           f.name AS failure,
           collect(DISTINCT all_s.condition) AS expected_symptoms,
           collect(DISTINCT a.name) AS required_actions
    """

    # Area/HSE hazards: zone-level failure modes (gas accumulation, heat stress, ...)
    # that apply even when no instrumented equipment is in the zone (e.g. corridor).
    ZONE_QUERY = """
    MATCH (z:Zone {id: $zone_id})-[:CAN_EXPERIENCE]->(f:FailureMode)
          -[:INDICATED_BY]->(trigger_s:Symptom)
    WHERE trigger_s.type IN $sensor_types
    MATCH (f)-[:INDICATED_BY]->(all_s:Symptom)
    MATCH (f)-[:REQUIRES_ACTION]->(a:Action)
    RETURN DISTINCT z.name AS zone_name,
           f.name AS failure,
           collect(DISTINCT all_s.condition) AS expected_symptoms,
           collect(DISTINCT a.name) AS required_actions
    """

    def get_llm_context(self, parsed_zone: str, parsed_sensors: list) -> str:
        """
        Queries device-level failure modes AND zone-level (area/HSE) hazards for
        the triggered sensors, formatted as a clean text block for the LLM.
        """
        try:
            with self.driver.session() as session:
                context_lines = []

                for record in session.run(self.DEVICE_QUERY, zone_id=parsed_zone, sensor_types=parsed_sensors):
                    symptoms_str = " AND ".join(record["expected_symptoms"])
                    actions_str = ", ".join(record["required_actions"])
                    model_str = f" (model {record['model']})" if record["model"] else ""
                    context_lines.append(
                        f"Device: '{record['device']}'{model_str}\n"
                        f"  - Possible Failure: {record['failure']}\n"
                        f"  - Expected Profile: Manifests strictly as {symptoms_str}\n"
                        f"  - Protocol: {actions_str}\n"
                    )

                for record in session.run(self.ZONE_QUERY, zone_id=parsed_zone, sensor_types=parsed_sensors):
                    symptoms_str = " AND ".join(record["expected_symptoms"])
                    actions_str = ", ".join(record["required_actions"])
                    context_lines.append(
                        f"Area Hazard in '{record['zone_name']}' (per HSE-2025-04, not tied to one device):\n"
                        f"  - Possible Hazard: {record['failure']}\n"
                        f"  - Expected Profile: Manifests strictly as {symptoms_str}\n"
                        f"  - Protocol: {actions_str}\n"
                    )

                # 3. Retrieve and format inter-equipment connectivity
                conn_records = session.run("""
                    MATCH (d1:Device)-[r:CONTROLS|FEEDS|SUPPLIES_AIR_TO]->(d2:Device)
                    RETURN d1.name AS src, type(r) AS rel, d2.name AS dst
                """)
                conn_lines = [f"- '{r['src']}' {r['rel']} '{r['dst']}'" for r in conn_records]

                # 4. Retrieve and format spatial zone connectivity
                spatial_records = session.run("""
                    MATCH (z1:Zone)-[r:CONNECTS_TO]->(z2:Zone)
                    RETURN z1.name AS src, type(r) AS rel, z2.name AS dst
                """)
                spatial_lines = [f"- '{r['src']}' {r['rel']} '{r['dst']}'" for r in spatial_records]

                if not context_lines:
                    return f"No known topological failure modes match the sensor alerts in {parsed_zone}."

                final_context = "=== KNOWLEDGE GRAPH TOPOLOGY ===\n" + "\n".join(context_lines)
                if conn_lines:
                    final_context += "\n\n=== INTER-EQUIPMENT CONNECTIVITY ===\n" + "\n".join(conn_lines)
                if spatial_lines:
                    final_context += "\n\n=== SPATIAL ZONE TOPOLOGY ===\n" + "\n".join(spatial_lines)
                return final_context

        except Exception as e:
            logging.error(f"Failed to extract subgraph: {e}")
            return f"Error extracting structural context: {e}"

# --- Verification Block ---
if __name__ == "__main__":
    # Simulating the output from Phase 2 (Query Generator)
    target_zone = "room_1"
    
    # Simulating ONLY a temperature alert (Missing the Vibration alert)
    active_sensors = ["temperature"] 
    
    print(f"--- Simulating Anomaly Event ---")
    print(f"Zone: {target_zone}")
    print(f"Alerts: {active_sensors}\n")
    
    extractor = SubgraphExtractor()
    llm_ready_text = extractor.get_llm_context(target_zone, active_sensors)
    
    print("--- Extracted Context for LLM Window ---")
    print(llm_ready_text)
    
    extractor.close()