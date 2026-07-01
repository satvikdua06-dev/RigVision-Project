from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Set

import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("rigvision")


REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None
_redis_pool = None

def _get_pool():
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.ConnectionPool.from_url(
            f"redis://{REDIS_HOST}:{REDIS_PORT}", password=REDIS_PASSWORD, decode_responses=True, max_connections=20
        )
    return _redis_pool

def get_redis():
    return aioredis.Redis(connection_pool=_get_pool())

SENSORS_KEY = "rigvision:sensors:latest"
ZONE_DEFS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cad", "zone_definitions.json"
)
_zone_defs_cache: Optional[dict] = None

# Maps rig zone ids → Neo4j knowledge-graph Zone ids (seed_graph.py uses room_1/room_2/corridor).
# Floor-1 variants reuse their ground-floor room's KG topology.
ZONE_TO_KG = {
    "zone_a": "room_1", "zone_b": "room_2", "corridor": "corridor",
    "zone_a_f1": "room_1", "zone_b_f1": "room_2", "corridor_f1": "corridor",
}

ALERTS_TOPIC = "rigvision_alerts"
_kafka_producer = None

def _get_kafka_producer():
    global _kafka_producer
    if _kafka_producer is None:
        from kafka import KafkaProducer
        _kafka_producer = KafkaProducer(
            bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
    return _kafka_producer

def _load_zone_defs() -> dict:
    """Load zone_definitions.json (cached). The single source of truth for which
    sensors exist, their units, and their thresholds."""
    global _zone_defs_cache
    if _zone_defs_cache is None:
        with open(ZONE_DEFS_PATH, "r", encoding="utf-8") as f:
            _zone_defs_cache = json.load(f)
    return _zone_defs_cache

def _build_sensor_manifest() -> dict:
    """Flatten zone_definitions.json into a UI-friendly manifest: zones, each with
    their sensors (id, type, unit, range, thresholds). The dashboard builds sliders
    dynamically from this — add a sensor to the JSON and it appears automatically."""
    defs = _load_zone_defs()
    zones_out = {}
    valid_ids = set()
    for zone_id, zdef in defs.get("zones", {}).items():
        sensors = []
        for s in zdef.get("sensors", []):
            valid_ids.add(s["id"])
            sensors.append({
                "id": s["id"],
                "type": s["type"],
                "unit": s.get("unit", ""),
                "normal_range": s.get("normal_range", [0, 100]),
                "warning": s.get("warning"),
                "critical": s.get("critical"),
                "position": s.get("position"),
            })
        zones_out[zone_id] = {
            "name": zdef.get("name", zone_id),
            "floor": zdef.get("floor", 0),
            "sensors": sensors,
        }
    return {"zones": zones_out, "valid_ids": valid_ids}

class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info("Client connected. Total: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info("Client disconnected. Total: %d", len(self.active_connections))

    async def broadcast(self, message: str):
        if not self.active_connections: return
        async def _safe_send(ws):
            try:
                await ws.send_text(message)
            except Exception:
                return ws
        results = await asyncio.gather(*(_safe_send(ws) for ws in self.active_connections), return_exceptions=True)
        for r in results:
            if isinstance(r, WebSocket): self.active_connections.discard(r)

    async def close_all(self):
        for ws in list(self.active_connections):
            try: await ws.close(code=1001, reason="Server shutting down")
            except Exception: pass
        self.active_connections.clear()

manager = ConnectionManager()


_active_mjpeg_streams = 0
MAX_MJPEG_STREAMS = 10

async def redis_to_websocket_bridge():
    r = get_redis()
    _prev_hash = None
    while True:
        try:
            if manager.active_connections:
                p_raw, z_raw, d_raw = await asyncio.gather(
                    r.get("rigvision:persons"),
                    r.get("rigvision:zones"),
                    r.get("rigvision:diagnostics"),
                )
                cur_hash = hash((p_raw, z_raw, d_raw))
                if cur_hash != _prev_hash:
                    _prev_hash = cur_hash
                    msg = {
                        "type": "realtime_update",
                        "timestamp": time.time(),
                        "persons": json.loads(p_raw) if p_raw else [],
                        "zones": json.loads(z_raw) if z_raw else {},
                        "diagnostics": json.loads(d_raw) if d_raw else [],
                    }
                    await manager.broadcast(json.dumps(msg))
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error("Bridge error: %s", e)
            await asyncio.sleep(1)

def start_kafka_consumer():
    import threading
    def _run():
        try:
            from kafka import KafkaConsumer
            import redis
            logger.info("Kafka diagnostics consumer thread started.")
            consumer = KafkaConsumer(
                "rigvision_diagnostics",
                bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
                auto_offset_reset="latest",
                consumer_timeout_ms=1000
            )
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)

            while True:
                records = consumer.poll(timeout_ms=500)
                for tp, messages in records.items():
                    for message in messages:
                        try:
                            # Diagnostics are self-describing (event_id, zone_id, severity,
                            # telemetry are stamped on by anomaly_listener) — just dedup + store.
                            diag = json.loads(message.value.decode("utf-8"))
                            diag.setdefault("timestamp", int(time.time() * 1000))
                            logger.info("Backend received diagnostic for zone %s", diag.get("zone_id"))

                            raw = r.get("rigvision:diagnostics")
                            diags = json.loads(raw) if raw else []
                            eid = diag.get("event_id")
                            if not eid or not any(d.get("event_id") == eid for d in diags):
                                diags.insert(0, diag)
                                r.set("rigvision:diagnostics", json.dumps(diags[:50]))
                        except Exception as e:
                            logger.error("Error processing diagnostic message: %s", e)
        except Exception as e:
            logger.error("Kafka consumer thread failed/stopped: %s", e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_redis().ping()
    start_kafka_consumer()
    bridge_task = asyncio.create_task(redis_to_websocket_bridge())
    yield
    bridge_task.cancel()
    await manager.close_all()
    await _get_pool().disconnect()

app = FastAPI(title="RigVision-3D API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://localhost:5173", "http://localhost:5174",
        "http://127.0.0.1:3000", "http://127.0.0.1:5173", "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

@app.get("/api/health")
async def health_check():
    try:
        await get_redis().ping()
        status = "connected"
    except Exception:
        status = "disconnected"
    return {"status": "ok", "redis": status, "websocket_clients": len(manager.active_connections), "timestamp": time.time()}

@app.get("/api/persons")
async def get_persons():
    raw = await get_redis().get("rigvision:persons")
    return json.loads(raw) if raw else []

@app.get("/api/zones")
async def get_zones():
    raw = await get_redis().get("rigvision:zones")
    return json.loads(raw) if raw else {}

@app.get("/api/diagnostics")
async def get_diagnostics():
    raw = await get_redis().get("rigvision:diagnostics")
    return json.loads(raw) if raw else []


@app.get("/api/video/mjpeg/{camera_id}")
async def get_mjpeg_stream(camera_id: str):
    global _active_mjpeg_streams
    if _active_mjpeg_streams >= MAX_MJPEG_STREAMS:
        raise HTTPException(status_code=503, detail="Too many streams")
    r = get_redis()
    if not await r.exists(f"rigvision:camera:frame:{camera_id}"):
        raise HTTPException(status_code=404, detail="Camera offline")
    async def frame_generator():
        global _active_mjpeg_streams
        _active_mjpeg_streams += 1
        missing_count = 0
        try:
            while True:
                jpeg_b64 = await r.get(f"rigvision:camera:frame:{camera_id}")
                if jpeg_b64:
                    missing_count = 0
                    jpeg_bytes = base64.b64decode(jpeg_b64)
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg_bytes)).encode() + b"\r\n\r\n" + jpeg_bytes + b"\r\n")
                else:
                    missing_count += 1
                    if missing_count >= 50: break
                await asyncio.sleep(0.04)
        finally:
            _active_mjpeg_streams -= 1
    return StreamingResponse(frame_generator(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.post("/api/control/clear_cache")
async def post_clear_cache():
    await get_redis().publish("rigvision:commands", "clear_cache")
    return {"status": "ok", "message": "clear_cache command published"}

@app.post("/api/diagnostics/run")
async def run_diagnostics():
    """On-demand diagnostics: threshold-check every zone against current sensor data,
    and publish one Kafka alert per FLAGGED zone (→ anomaly_listener → LLM). If no zone
    breaches a threshold, returns 'all_clear' without invoking the LLM."""
    sensors_raw = await get_redis().get(SENSORS_KEY)
    sensors = json.loads(sensors_raw) if sensors_raw else {}
    manifest = _build_sensor_manifest()

    now = int(time.time())
    alerts = []
    for zid, zone in manifest["zones"].items():
        telemetry, triggered, sev_rank = {}, [], 0
        for s in zone["sensors"]:
            reading = sensors.get(s["id"])
            if not reading or reading.get("value") is None:
                continue
            val = float(reading["value"])
            telemetry[s["type"]] = val
            crit, warn = s.get("critical"), s.get("warning")
            if crit is not None and val >= crit:
                triggered.append(s["type"]); sev_rank = max(sev_rank, 2)
            elif warn is not None and val >= warn:
                triggered.append(s["type"]); sev_rank = max(sev_rank, 1)
        if triggered:
            alerts.append({
                "event_id": f"anom_{now}_{zid}",
                "zone_id": ZONE_TO_KG.get(zid, zid),   # KG lookup id
                "rig_zone_id": zid,                     # rig id for display
                "severity": "CRITICAL" if sev_rank == 2 else "HIGH",
                "triggered_sensors": sorted(set(triggered)),
                "telemetry_snapshot": telemetry,
                "timestamp": now * 1000,
            })

    if not alerts:
        return {"status": "all_clear", "zones_checked": len(manifest["zones"]), "flagged": [], "alerts_published": 0}

    def _publish(items):
        producer = _get_kafka_producer()
        for it in items:
            producer.send(ALERTS_TOPIC, it)
        producer.flush()

    try:
        await asyncio.to_thread(_publish, alerts)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kafka publish failed: {e}")

    return {
        "status": "flagged",
        "zones_checked": len(manifest["zones"]),
        "flagged": [a["rig_zone_id"] for a in alerts],
        "alerts_published": len(alerts),
    }

# ── Sensor ingestion (the seam) ──────────────────────────────────────────
# Producers (manual dashboard now, MQTT bridge later) write rigvision:sensors:latest.
# The CV pipeline reads it. Swap the producer, the pipeline never changes.

class SensorReadingsRequest(BaseModel):
    readings: Dict[str, float]   # { sensor_id: value }
    source: str = "manual"       # "manual" | "mqtt" | "sim"

@app.get("/api/sensors/manifest")
async def get_sensor_manifest():
    """Returns the sensor list (grouped by zone) so the dashboard builds sliders
    dynamically from zone_definitions.json."""
    m = _build_sensor_manifest()
    return {"zones": m["zones"]}

@app.get("/api/sensors")
async def get_sensors():
    """Current values of rigvision:sensors:latest (to populate sliders on open)."""
    raw = await get_redis().get(SENSORS_KEY)
    return json.loads(raw) if raw else {}

@app.post("/api/sensors")
async def post_sensors(body: SensorReadingsRequest):
    """Validated merge-write into rigvision:sensors:latest. Unknown sensor IDs
    (not in zone_definitions.json) are rejected."""
    valid_ids = _build_sensor_manifest()["valid_ids"]
    unknown = [sid for sid in body.readings if sid not in valid_ids]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown sensor IDs: {unknown}")

    r = get_redis()
    raw = await r.get(SENSORS_KEY)
    current = json.loads(raw) if raw else {}

    now = int(time.time())
    for sid, value in body.readings.items():
        current[sid] = {"value": value, "updated_at": now, "source": body.source}

    await r.set(SENSORS_KEY, json.dumps(current))
    return {"status": "ok", "updated": list(body.readings.keys()), "count": len(current)}

@app.websocket("/ws/realtime")
async def websocket_realtime(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data:
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                except Exception: pass
    except (WebSocketDisconnect, Exception):
        manager.disconnect(websocket)

if __name__ == "__main__":
    uvicorn.run("main:app", host=os.getenv("BACKEND_HOST", "0.0.0.0"), port=int(os.getenv("BACKEND_PORT", "8000")), reload=True, log_level="info")
