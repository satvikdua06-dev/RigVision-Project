"""
MQTT broker worker — one thread per broker.

Uses paho-mqtt's loop_start() which runs its own internal network thread.
The on_message callback pushes RawReadings into the shared queue — safe
because queue.Queue is thread-safe.

Config keys (from mqtt_topics.yaml broker entry):
  host, port
  subscriptions[]:
    topic      — MQTT topic string (exact match, no wildcards per entry)
    sensor_id  — must match zone_definitions.json
    scale, offset, unit
"""
from __future__ import annotations

import json
import logging
import time

import paho.mqtt.client as mqtt

from .base import PortWorker, RawReading

log = logging.getLogger(__name__)

_BACKOFF_MAX = 30


class MQTTWorker(PortWorker):

    def run(self) -> None:
        cfg  = self.config
        host = cfg["host"]
        port = int(cfg.get("port", 1883))
        subs = cfg.get("subscriptions", [])

        if not subs:
            log.warning(f"[mqtt] {host}:{port} — no subscriptions configured, exiting")
            return

        topic_map: dict[str, dict] = {s["topic"]: s for s in subs}

        # ── Callbacks ─────────────────────────────────────────────────────────
        def on_connect(client, userdata, flags, rc, properties=None):
            if rc == 0:
                log.info(f"[mqtt] Connected to {host}:{port}")
                for s in subs:
                    client.subscribe(s["topic"], qos=1)
            else:
                log.warning(f"[mqtt] {host}:{port} — connect rc={rc}")

        def on_disconnect(client, userdata, disconnect_flags, rc, properties=None):
            if rc != 0:
                log.warning(f"[mqtt] {host}:{port} — unexpected disconnect rc={rc}")

        def on_message(client, userdata, msg):
            sub_cfg = topic_map.get(msg.topic)
            if not sub_cfg:
                return
            try:
                payload = msg.payload.decode("utf-8", errors="replace")
                try:
                    data = json.loads(payload)
                    if isinstance(data, dict):
                        raw_val = float(data.get("value", 0))
                    else:
                        raw_val = float(data)
                except (json.JSONDecodeError, TypeError, ValueError):
                    raw_val = float(payload)
            except Exception as e:
                log.warning(f"[mqtt] parse error {msg.topic}: {e}")
                return

            self.queue.put(RawReading(
                sensor_id=sub_cfg["sensor_id"],
                raw_value=raw_val,
                protocol="mqtt",
                device=f"{host}:{port}",
                config=sub_cfg,
            ))

        # ── Connect + loop ─────────────────────────────────────────────────────
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, clean_session=True,
                             client_id=f"rigvision-scada-{host}")
        client.on_connect    = on_connect
        client.on_disconnect = on_disconnect
        client.on_message    = on_message

        backoff = 1
        while not self._stop.is_set():
            try:
                client.connect(host, port, keepalive=60)
                client.loop_start()
                # Block here; paho's network loop runs in its own internal thread
                while not self._stop.is_set():
                    time.sleep(1)
                client.loop_stop()
                client.disconnect()
                break
            except Exception as e:
                log.warning(f"[mqtt] {host}:{port} — {e}, retry in {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)

        log.info(f"[mqtt] {host}:{port} stopped")
