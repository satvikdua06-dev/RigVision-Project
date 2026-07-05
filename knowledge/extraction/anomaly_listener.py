import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import redis
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

# How many alerts to diagnose concurrently. The Neo4j fetch + embedding + Chroma
# stages overlap across workers; LM Studio (n_parallel=1) still serializes the
# generation step, so a small pool is plenty.
LISTENER_WORKERS = int(os.environ.get("LISTENER_WORKERS", "3"))

# Redis is used ONLY to stream per-stage progress to the live diagnostics window
# (the final diagnostic still goes out over Kafka). Progress for each event is one
# field in the `rigvision:diag:progress` hash; the backend WS bridge relays + prunes it.
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "") or None
PROGRESS_KEY = "rigvision:diag:progress"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

_redis = None
_redis_lock = threading.Lock()


def get_redis():
    global _redis
    if _redis is None:
        with _redis_lock:
            if _redis is None:
                _redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT,
                                     password=REDIS_PASSWORD, decode_responses=True)
    return _redis


def publish_progress(progress: dict):
    """Write the accumulated progress object for one event into the progress hash.
    Best-effort: progress streaming must never break the diagnosis itself."""
    eid = progress.get("event_id")
    if not eid:
        return
    progress["updated_at"] = int(time.time() * 1000)
    try:
        r = get_redis()
        r.hset(PROGRESS_KEY, eid, json.dumps(progress))
        r.expire(PROGRESS_KEY, 600)  # safety net so the hash can't grow forever
    except Exception as e:
        logging.warning("Could not publish progress for %s: %s", eid, e)

# --- Lazy singletons ---
# Built on first use (not at import) so the process can start and connect to
# Kafka even if ChromaDB / Neo4j are briefly unavailable. Both are reused across
# messages — the SubgraphExtractor holds one Neo4j driver/pool for the whole run
# instead of opening a fresh connection per alert.
_agent = None
_extractor = None
_singleton_lock = threading.Lock()  # guards lazy init under the worker pool


def get_agent() -> LLMDiagnosticAgent:
    global _agent
    if _agent is None:
        with _singleton_lock:
            if _agent is None:
                _agent = LLMDiagnosticAgent()
    return _agent


def get_extractor() -> SubgraphExtractor:
    global _extractor
    if _extractor is None:
        with _singleton_lock:
            if _extractor is None:
                _extractor = SubgraphExtractor()
    return _extractor


def process_anomaly_message(payload_str):
    """
    Orchestrates the knowledge extraction pipeline, streaming per-stage progress to
    the live diagnostics window via Redis as it goes.
    """
    logging.info("Processing anomaly message")

    # Progress object accumulates across stages (subgraph + chunks are kept so the
    # window can display them); re-published to Redis at every stage transition.
    full_telemetry_data = {}
    progress = {}
    try:
        full_telemetry_data = json.loads(payload_str)
    except json.JSONDecodeError as e:
        logging.error(f"Failed to decode JSON payload: {e}")
        return None

    eid = full_telemetry_data.get("event_id")
    zid = full_telemetry_data.get("rig_zone_id") or full_telemetry_data.get("zone_id")
    progress = {
        "event_id": eid,
        "zone_id": zid,
        "severity": full_telemetry_data.get("severity"),
        "triggered_sensors": full_telemetry_data.get("triggered_sensors"),
        "stage": "generating_query",
        "started_at": int(time.time() * 1000),
    }

    try:
        # 1. Parse + validate the incoming payload → KG query params.
        publish_progress(progress)
        logging.info("Step 1: Parsing anomaly payload...")
        query_params = AnomalyQueryBuilder.process_payload(payload_str)
        parsed_zone = query_params["zone_id"]
        parsed_sensors = query_params["sensor_types"]
        progress["sensor_types"] = parsed_sensors
        logging.info(f"  - Parsed Zone: {parsed_zone} | Sensors: {parsed_sensors}")

        # 2. Extract the subgraph (reuses one shared Neo4j driver across messages).
        progress["stage"] = "getting_subgraph"
        publish_progress(progress)
        logging.info("Step 2: Extracting subgraph from Knowledge Graph...")
        extractor = get_extractor()
        llm_context = extractor.get_llm_context(
            parsed_zone=parsed_zone, parsed_sensors=parsed_sensors
        )
        progress["stage"] = "subgraph_ready"
        progress["subgraph"] = llm_context
        publish_progress(progress)
        logging.debug("LLM CONTEXT READY:\n%s", llm_context)

        # 3. Retrieve manual chunks (embed query + Chroma search).
        progress["stage"] = "getting_chunks"
        publish_progress(progress)
        logging.info("Step 3: Retrieving manual chunks...")
        agent = get_agent()
        manuals_context = agent.retrieve_manuals(llm_context)
        progress["stage"] = "chunks_ready"
        progress["chunks"] = manuals_context
        publish_progress(progress)

        # 4. Generate the diagnosis with the local LLM.
        progress["stage"] = "writing_answer"
        publish_progress(progress)
        logging.info("Step 4: Generating diagnostic report with LLM Agent...")
        diagnostic_report_json = agent.generate_answer(
            telemetry=full_telemetry_data,
            graph_context=llm_context,
            manuals_context=manuals_context,
        )

        # Parse the model output. A non-JSON or {"error": ...} response means the
        # diagnosis failed — drop it rather than publishing a bogus diagnostic card.
        try:
            report = json.loads(diagnostic_report_json)
        except (json.JSONDecodeError, TypeError):
            logging.error("LLM returned non-JSON; dropping diagnostic for event %s", eid)
            progress["stage"] = "error"
            progress["error"] = "Model returned non-JSON output"
            publish_progress(progress)
            return None
        if not isinstance(report, dict) or "error" in report:
            err = report.get("error") if isinstance(report, dict) else str(report)
            logging.error("LLM diagnosis failed for event %s: %s", eid, err)
            progress["stage"] = "error"
            progress["error"] = err
            publish_progress(progress)
            return None

        # Make the diagnostic self-describing: stamp the source alert's identity onto
        # it so multiple concurrent zone alerts don't get mis-correlated downstream.
        report["event_id"] = eid
        report["zone_id"] = zid     # rig-facing id (zone_a/zone_b) for display
        report["severity"] = full_telemetry_data.get("severity")
        report["triggered_sensors"] = full_telemetry_data.get("triggered_sensors")
        report["telemetry_snapshot"] = full_telemetry_data.get("telemetry_snapshot")
        # Manual-grounded explanation of WHY each sensor was flagged.
        report["threshold_context"] = full_telemetry_data.get("threshold_context")
        report["timestamp"] = int(time.time() * 1000)
        report["subgraph"] = llm_context
        report["chunks"] = manuals_context

        # Final stage: carry the full report so the live window renders it without
        # waiting for the Kafka→Redis round-trip.
        progress["stage"] = "done"
        progress["report"] = report
        publish_progress(progress)

        return json.dumps(report)

    except ValueError as e:
        logging.error(f"Payload validation failed: {e}")
        progress["stage"], progress["error"] = "error", str(e)
        publish_progress(progress)
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred during processing: {e}")
        progress["stage"], progress["error"] = "error", str(e)
        publish_progress(progress)
        return None


def _handle_message(payload_str, producer):
    """Worker body: diagnose one alert and publish the result. Runs in the pool, so
    it must swallow its own exceptions (a raised worker would be lost silently)."""
    try:
        diagnostic_report_json = process_anomaly_message(payload_str)
        if diagnostic_report_json:
            producer.send(KAFKA_TOPIC_DIAGNOSTICS, diagnostic_report_json)
            producer.flush()
            logging.info(f"Diagnostic report published to '{KAFKA_TOPIC_DIAGNOSTICS}'.")
    except Exception as e:
        logging.error(f"Worker failed to handle alert: {e}")


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
    logging.info("Starting anomaly listener (%d workers)... Waiting for alerts.", LISTENER_WORKERS)

    pool = ThreadPoolExecutor(max_workers=LISTENER_WORKERS)
    try:
        # Dispatch each alert to the pool so concurrent zone alerts diagnose in
        # parallel instead of head-of-line blocking on one slow LLM call.
        for message in consumer:
            logging.info(f"Received message on topic '{message.topic}'")
            pool.submit(_handle_message, message.value, producer)

    except KeyboardInterrupt:
        logging.info("Listener stopped by user.")
    except Exception as e:
        logging.error(f"An error occurred in the consumer loop: {e}")
    finally:
        pool.shutdown(wait=True)
        consumer.close()
        producer.close()
        if _extractor is not None:
            _extractor.close()
            logging.info("Cleanly closed Neo4j connection.")
        logging.info("Disconnected from Kafka broker.")


if __name__ == "__main__":
    main()