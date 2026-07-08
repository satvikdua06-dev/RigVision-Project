"""
MQTT Publisher Simulator — Zone B sensors
==========================================
Publishes zone_b sensor values to an MQTT broker (default localhost:1883)
at 1 Hz.  Values are STATIC by default.  The sensor console writes set-points
to Redis at  scada:setpoints  (HSET), and the publisher reads them each tick
so the MQTT feed reflects the latest manual values.

Topics (matching scada/config/mqtt_topics.yaml):
  rig/zone_b/temp_b
  rig/zone_b/vib_b
  rig/zone_b/gas_b
  rig/zone_b/noise_b
  rig/zone_b/pressure_b

Payload per topic: JSON  {"sensor_id": "<id>", "value": <float>}

Requires a running MQTT broker.  Install Mosquitto:
  Windows: https://mosquitto.org/download/
  Docker:  docker run -d -p 1883:1883 eclipse-mosquitto

Run:
  python -m scada.simulators.mqtt_publisher
  python scada/simulators/mqtt_publisher.py
"""
import json
import logging
import os
import time
from pathlib import Path

import paho.mqtt.client as mqtt

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)
except ImportError:
    pass

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

BROKER_HOST = os.getenv("MQTT_HOST",         "localhost")
BROKER_PORT = int(os.getenv("MQTT_PORT",     "1883"))
INTERVAL    = float(os.getenv("MQTT_SIM_INTERVAL", "1.0"))

# (topic, sensor_id) — no oscillation function
_SENSORS = [
    ("rig/zone_b/temp_b",     "temp_b"),
    ("rig/zone_b/vib_b",      "vib_b"),
    ("rig/zone_b/gas_b",      "gas_b"),
    ("rig/zone_b/noise_b",    "noise_b"),
    ("rig/zone_b/pressure_b", "pressure_b"),
]

# Static defaults (no oscillation)
_DEFAULTS = {
    "temp_b":     29.0,
    "vib_b":      1.0,
    "gas_b":      2.0,
    "noise_b":    70.0,
    "pressure_b": 11.0,
}

# Current published values — updated from Redis each tick
_current: dict[str, float] = dict(_DEFAULTS)


def _make_client() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id="rigvision-mqtt-sim")

    def on_connect(c, userdata, flags, rc, properties=None):
        if rc == 0:
            log.info(f"Connected to MQTT broker {BROKER_HOST}:{BROKER_PORT}")
        else:
            log.error(f"MQTT connect failed rc={rc}")

    client.on_connect = on_connect
    return client


def _connect_with_retry(client: mqtt.Client) -> bool:
    """Try to connect; return True on success, False if refused (no broker)."""
    backoff = 2
    while True:
        try:
            client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
            return True
        except ConnectionRefusedError:
            log.warning(
                f"[mqtt-sim] Broker not available at {BROKER_HOST}:{BROKER_PORT} "
                f"- retrying in {backoff}s "
                f"(start Mosquitto: docker run -d -p 1883:1883 eclipse-mosquitto)"
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
        except KeyboardInterrupt:
            return False
        except Exception as e:
            log.warning(f"[mqtt-sim] Connect error: {e} - retrying in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)


def _connect_redis():
    try:
        import redis as redis_lib
        r = redis_lib.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
        )
        r.ping()
        log.info("[mqtt-sim] Redis connected — reading setpoints from scada:setpoints")
        return r
    except Exception as e:
        log.warning(f"[mqtt-sim] Redis unavailable ({e}) — using static defaults")
        return None


def main() -> None:
    global _current
    client = _make_client()

    log.info(f"MQTT simulator - will publish {len(_SENSORS)} zone_b topics every {INTERVAL}s")
    log.info(f"Waiting for broker at {BROKER_HOST}:{BROKER_PORT} ...")

    if not _connect_with_retry(client):
        return

    client.loop_start()
    redis_client = _connect_redis()

    tick = 0
    try:
        while True:
            # Refresh values from Redis setpoints each tick
            if redis_client:
                try:
                    setpoints = redis_client.hgetall("scada:setpoints")
                    for sid, raw_str in setpoints.items():
                        if sid in _current:
                            _current[sid] = float(raw_str)
                except Exception as e:
                    log.warning(f"[mqtt-sim] Redis read error: {e}")

            for topic, sensor_id in _SENSORS:
                value   = round(_current.get(sensor_id, _DEFAULTS[sensor_id]), 3)
                payload = json.dumps({"sensor_id": sensor_id, "value": value})
                result  = client.publish(topic, payload, qos=1, retain=True)
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    log.warning(f"Publish failed for {topic}: rc={result.rc}")

            if tick % 10 == 0:
                log.info("  ".join(f"{sid}={v:.2f}" for sid, v in _current.items()))

            tick += 1
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        log.info("Stopped.")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
