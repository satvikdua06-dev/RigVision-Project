import logging
import os
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_topology(tx):

    tx.run("MATCH (n) DETACH DELETE n")
    
    query = """
    CREATE (r1:Zone {id: 'room_1', name: 'Room 1'})
    CREATE (r2:Zone {id: 'room_2', name: 'Room 2'})
    CREATE (c1:Zone {id: 'corridor', name: 'Corridor'})


    CREATE (ac:Device {id: 'ac_unit', name: 'AC Unit'})
    CREATE (cf:Device {id: 'ceiling_fan', name: 'Ceiling Fan'})
    CREATE (ef:Device {id: 'exhaust_fan', name: 'Exhaust Fan'})
    CREATE (gs:Device {id: 'gas_stove', name: 'Gas Stove'})
    CREATE (lf:Device {id: 'light_fixture', name: 'Light Fixture'})

    // Link Devices to Zones
    CREATE (r1)-[:CONTAINS]->(ac)
    CREATE (r1)-[:CONTAINS]->(cf)
    CREATE (r2)-[:CONTAINS]->(ef)
    CREATE (r2)-[:CONTAINS]->(gs)
    CREATE (c1)-[:CONTAINS]->(lf)

    // 3. Create Failure Modes
    CREATE (fm_ac1:FailureMode {id: 'fm_compressor_failure', name: 'Compressor Failure'})
    CREATE (fm_ac2:FailureMode {id: 'fm_refrigerant_leak', name: 'Refrigerant Leak'})
    CREATE (fm_cf:FailureMode {id: 'fm_motor_degradation', name: 'Motor Degradation'})
    CREATE (fm_ef:FailureMode {id: 'fm_burnout', name: 'Motor Burnout'})
    CREATE (fm_gs:FailureMode {id: 'fm_valve_leak', name: 'Valve Leak'})
    CREATE (fm_lf:FailureMode {id: 'fm_ballast_failure', name: 'Ballast Failure'})

    // Link Devices to Failure Modes
    CREATE (ac)-[:CAN_EXPERIENCE]->(fm_ac1)
    CREATE (ac)-[:CAN_EXPERIENCE]->(fm_ac2)
    CREATE (cf)-[:CAN_EXPERIENCE]->(fm_cf)
    CREATE (ef)-[:CAN_EXPERIENCE]->(fm_ef)
    CREATE (gs)-[:CAN_EXPERIENCE]->(fm_gs)
    CREATE (lf)-[:CAN_EXPERIENCE]->(fm_lf)

    // 4. Create Symptoms
    CREATE (s_temp:Symptom {type: 'temperature', condition: 'High Temperature'})
    CREATE (s_vib:Symptom {type: 'vibration', condition: 'High Vibration'})
    CREATE (s_noise:Symptom {type: 'noise', condition: 'High Noise'})
    CREATE (s_gas:Symptom {type: 'gas', condition: 'Gas Leak'})

    // 5. Link Failure Modes to Symptoms
    CREATE (fm_ac1)-[:INDICATED_BY]->(s_temp)
    CREATE (fm_ac1)-[:INDICATED_BY]->(s_vib)

    CREATE (fm_ac2)-[:INDICATED_BY]->(s_temp)

    CREATE (fm_cf)-[:INDICATED_BY]->(s_temp)
    CREATE (fm_cf)-[:INDICATED_BY]->(s_vib)

    CREATE (fm_ef)-[:INDICATED_BY]->(s_temp)
    CREATE (fm_ef)-[:INDICATED_BY]->(s_noise)

    CREATE (fm_gs)-[:INDICATED_BY]->(s_gas)
    CREATE (fm_gs)-[:INDICATED_BY]->(s_temp)
    CREATE (fm_lf)-[:INDICATED_BY]->(s_temp)
    CREATE (fm_lf)-[:INDICATED_BY]->(s_noise)

    // Require Action
    CREATE (s_valve:Action {type: 'Valve', condition: 'Fix Valve'})
    CREATE (s_motor:Action {type: 'Motor', condition: 'Replace Motor'})
    CREATE (s_cfmotor:Action {type: 'cf_Motor', condition: 'Rewind Motor Coils'})
    CREATE (s_refrigerant:Action {type: 'Refrigerant', condition: 'Recharge Refrigerant'})
    CREATE (s_compressor:Action {type: 'Compressor', condition: 'Replace Compressor'})
    CREATE (s_led:Action {type: 'LED', condition: 'Replace LED Driver'})

    // 5. Link Failure Modes to Symptoms
    CREATE (fm_ac1)-[:REQUIRE_ACTION]->(s_compressor)
    CREATE (fm_ac2)-[:REQUIRE_ACTION]->(s_refrigerant)
    CREATE (fm_cf)-[:REQUIRE_ACTION]->(s_cfmotor)
    CREATE (fm_ef)-[:REQUIRE_ACTION]->(s_motor)
    CREATE (fm_gs)-[:REQUIRE_ACTION]->(s_valve)
    CREATE (fm_lf)-[:REQUIRE_ACTION]->(s_led)
    """
    tx.run(query)
    logging.info("Topology successfully created.")

def main():
    try:
        # Read connection details from environment variables with sensible defaults for local dev
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "rigvision_neo4j")
        auth = (user, password)

        driver = GraphDatabase.driver(uri, auth=auth)
        driver.verify_connectivity()
        logging.info("Connected to Neo4j successfully.")
        
        with driver.session() as session:
            session.execute_write(create_topology)
            
    except ServiceUnavailable as e:
        logging.error(f"Failed to connect to Neo4j. Is the Docker container running? Error: {e}")
    finally:
        if 'driver' in locals():
            driver.close()

if __name__ == "__main__":
    main()