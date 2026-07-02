import json
import logging
import os
import sys
import time
from kafka import KafkaConsumer, KafkaProducer

# Path hack to import from sibling directory 'agent_layer'
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the existing components from neighboring files
from query_generator import AnomalyQueryBuilder
from graph_extractor import SubgraphExtractor
from agent_layer.diagnostic_agent import LLMDiagnosticAgent

# --- Configuration ---
KAFKA_BROKER = os.environ.get("KAFKA_BROKER", "localhost")
KAFKA_PORT = int(os.environ.get("KAFKA_PORT", "9092"))
KAFKA_TOPIC_ALERTS = os.environ.get("KAFKA_TOPIC_ALERTS", "rigvision_alerts")
KAFKA_TOPIC_DIAGNOSTICS = os.environ.get("KAFKA_TOPIC_DIAGNOSTICS", "rigvision_diagnostics")

# --- Initializations ---
agent = LLMDiagnosticAgent()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def process_anomaly_message(payload_str):
    """
    Orchestrates the knowledge extraction pipeline.
    """
    logging.info("Processing anomaly message")

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

            # 4. Print the resulting LLM context string to the console.
            logging.info("Step 3: Context extracted. Passing to LLM Agent.")
            print("\n" + "="*50)
            print("LLM CONTEXT READY")
            print("="*50)
            print(llm_context)
            print("="*50 + "\n")

            # --- PHASE 5: CLOSED LOOP DIAGNOSIS ---
            logging.info("Step 4: Generating diagnostic report with LLM Agent...")
            full_telemetry_data = json.loads(payload_str)
            diagnostic_report_json = agent.generate_report(
                telemetry=full_telemetry_data,
                graph_context=llm_context
            )

            # Make the diagnostic self-describing: stamp the source alert's identity onto
            # it so multiple concurrent zone alerts don't get mis-correlated downstream.
            try:
                report = json.loads(diagnostic_report_json)
                report["event_id"] = full_telemetry_data.get("event_id")
                # Prefer the rig-facing zone id (zone_a/zone_b/...) for display.
                report["zone_id"] = full_telemetry_data.get("rig_zone_id") or full_telemetry_data.get("zone_id")
                report["severity"] = full_telemetry_data.get("severity")
                report["triggered_sensors"] = full_telemetry_data.get("triggered_sensors")
                report["telemetry_snapshot"] = full_telemetry_data.get("telemetry_snapshot")
                # Manual-grounded explanation of WHY each sensor was flagged
                # (which device/manual threshold fired) — carried to the frontend.
                report["threshold_context"] = full_telemetry_data.get("threshold_context")
                report["timestamp"] = int(time.time() * 1000)
                diagnostic_report_json = json.dumps(report)
            except (json.JSONDecodeError, TypeError):
                pass  # if the model returned non-JSON, pass it through unchanged

            return diagnostic_report_json

        finally:
            # 6. Ensure the database connection is always closed cleanly
            extractor.close()
            logging.info("Cleanly closed Neo4j connection.")

    except json.JSONDecodeError as e:
        logging.error(f"Failed to decode JSON payload: {e}")
        return None
    except ValueError as e:
        logging.error(f"Payload validation failed: {e}")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred during processing: {e}")
        return None


# --- Main Execution ---

def main():
    """Sets up the Kafka consumer and starts the listener loop."""
    bootstrap_servers = f"{KAFKA_BROKER}:{KAFKA_PORT}"

    # Initialize Kafka consumer
    consumer = KafkaConsumer(
        KAFKA_TOPIC_ALERTS,
        bootstrap_servers=[bootstrap_servers],
        group_id='anomaly_listener_v2',   # fresh group → ignores the old backlog offsets
        auto_offset_reset='latest',        # only react to NEW alerts, not replay the backlog
        value_deserializer=lambda x: x.decode('utf-8'),
        session_timeout_ms=30000
    )

    # Initialize Kafka producer
    producer = KafkaProducer(
        bootstrap_servers=[bootstrap_servers],
        value_serializer=lambda x: x.encode('utf-8')
    )

    logging.info(f"Connected to Kafka broker at {bootstrap_servers}")
    logging.info(f"Listening on topic: {KAFKA_TOPIC_ALERTS}")
    logging.info("Starting anomaly listener... Waiting for alerts.")

    try:
        # Listen for messages
        for message in consumer:
            logging.info(f"Received message on topic '{message.topic}'")
            payload_str = message.value

            # Process the anomaly message
            diagnostic_report_json = process_anomaly_message(payload_str)

            # Publish diagnostic result if successful
            if diagnostic_report_json:
                producer.send(KAFKA_TOPIC_DIAGNOSTICS, diagnostic_report_json)
                logging.info(f"Step 5: Diagnostic report published to '{KAFKA_TOPIC_DIAGNOSTICS}'.")
            # --- END PHASE 5 ---

    except KeyboardInterrupt:
        logging.info("Listener stopped by user.")
    except Exception as e:
        logging.error(f"An error occurred in the consumer loop: {e}")
    finally:
        consumer.close()
        producer.close()
        logging.info("Disconnected from Kafka broker.")


if __name__ == "__main__":
    main()