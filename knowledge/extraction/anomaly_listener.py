import json
import logging
import os
import paho.mqtt.client as mqtt

# Import the existing components from neighboring files
from query_generator import AnomalyQueryBuilder
from graph_extractor import SubgraphExtractor

# --- Configuration ---
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "rigvision/alerts")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')



def on_connect(client, userdata, flags, reason_code, properties):
    """Callback for when the client connects to the broker (V2 API)."""
    if reason_code == 0:
        logging.info(f"Connected to MQTT Broker at {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC)
        logging.info(f"Subscribed to topic: {MQTT_TOPIC}")
    else:
        logging.error(f"Failed to connect, return code {reason_code}\n")

def on_message(client, userdata, msg):
    """
    Callback for when a message is received.
    This function orchestrates the knowledge extraction pipeline.
    """
    logging.info(f"Received message on topic '{msg.topic}'")
    
    payload_str = msg.payload.decode('utf-8')
    
    try:
        # 1. Use AnomalyQueryBuilder to parse the incoming payload
        logging.info("Step 1: Parsing anomaly payload...")
        query_params = AnomalyQueryBuilder.process_payload(payload_str)
        
        parsed_zone = query_params["zone_id"]
        parsed_sensors = query_params["sensor_types"]
        
        logging.info(f"  - Parsed Zone: {parsed_zone}")
        logging.info(f"  - Parsed Sensors: {parsed_sensors}")

        # 2. Initialize SubgraphExtractor to connect to Neo4j
        logging.info("Step 2: Extracting subgraph from Knowledge Graph...")
        extractor = SubgraphExtractor()
        
        try:
            # 3. Pass parsed data to get the final context string
            llm_context = extractor.get_llm_context(
                parsed_zone=parsed_zone,
                parsed_sensors=parsed_sensors
            )
            
            # 4. Print the final output to the console
            logging.info("Step 3: Formatting complete. Final context below.")
            print("\n" + "="*50)
            print("LLM CONTEXT READY")
            print("="*50)
            print(llm_context)
            print("="*50 + "\n")

        finally:
            # 5. Ensure the database connection is always closed cleanly
            extractor.close()
            logging.info("Cleanly closed Neo4j connection.")

    except json.JSONDecodeError as e:
        logging.error(f"Failed to decode JSON payload: {e}")
    except ValueError as e:
        logging.error(f"Payload validation failed: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred during processing: {e}")

# --- Main Execution ---

def main():
    """Sets up the MQTT client and starts the listener loop."""
    # Pass the V2 API version explicitly
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        logging.info("Starting anomaly listener... Waiting for alerts.")
        client.loop_forever()
    except ConnectionRefusedError:
        logging.error(f"Connection to MQTT broker at {MQTT_BROKER}:{MQTT_PORT} was refused. Is it running?")
    except KeyboardInterrupt:
        logging.info("Listener stopped by user.")
    finally:
        client.disconnect()
        logging.info("Disconnected from MQTT broker.")

if __name__ == "__main__":
    main()