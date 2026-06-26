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

    def get_llm_context(self, parsed_zone: str, parsed_sensors: list) -> str:
        """
        Executes the Two-Step Match Cypher query and formats the extracted 
        subgraph into a clean text block for the LLM's context window.
        """
        # Step 1 & 2: Find suspects based on trigger, then fetch ALL their expected symptoms
        cypher_query = """
        // 1. Find suspect failures connected to the triggered sensors
        MATCH (z:Zone {id: $zone_id})-[:CONTAINS]->(d:Device)-[:CAN_EXPERIENCE]->(f:FailureMode)-[:INDICATED_BY]->(trigger_s:Symptom)
        WHERE trigger_s.type IN $sensor_types
        
        // 2. Fetch ALL expected symptoms and actions for those specific failures
        MATCH (f)-[:INDICATED_BY]->(all_s:Symptom)
        MATCH (f)-[:REQUIRE_ACTION]->(a:Action)
        
        RETURN d.name AS device, 
               f.name AS failure, 
               collect(DISTINCT all_s.condition) AS expected_symptoms,
               collect(DISTINCT a.condition) AS required_actions
        """

        try:
            with self.driver.session() as session:
                records = session.run(
                    cypher_query, 
                    zone_id=parsed_zone, 
                    sensor_types=parsed_sensors
                )
                
                context_lines = []
                for record in records:
                    symptoms_str = " AND ".join(record["expected_symptoms"])
                    actions_str = ", ".join(record["required_actions"])
                    
                    # Formatting explicitly for the LLM's reading comprehension
                    line = (
                        f"Device: '{record['device']}'\n"
                        f"  - Possible Failure: {record['failure']}\n"
                        f"  - Expected Profile: Manifests strictly as {symptoms_str}\n"
                        f"  - Protocol: {actions_str}\n"
                    )
                    context_lines.append(line)

                if not context_lines:
                    return f"No known topological failure modes match the sensor alerts in {parsed_zone}."

                # Wrap the extracted lines in a clear header
                final_context = "=== KNOWLEDGE GRAPH TOPOLOGY ===\n" + "\n".join(context_lines)
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