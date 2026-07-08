from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import struct
import sys
import time
from contextlib import asynccontextmanager
from typing import Dict, Optional, Set

# Allow `python backend/main.py` from any cwd to import backend/services/*.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
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
# Per-event live diagnosis progress (anomaly_listener writes; bridge relays + prunes).
PROGRESS_KEY = "rigvision:diag:progress"
PROGRESS_TTL_MS = 120_000  # drop progress entries older than this
ZONE_DEFS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cad", "zone_definitions.json"
)
_zone_defs_cache: Optional[dict] = None

# Maps rig zone ids → Neo4j knowledge-graph Zone ids (seed_graph.py uses room_1/room_2).
# Layout is two stacked rooms: zone_a = Room A (floor 0), zone_b = Room B (floor 1).
ZONE_TO_KG = {
    "zone_a": "room_1", "zone_b": "room_2",
}

from services.anomaly_evaluator import evaluate as evaluate_threshold
from services.threshold_resolver import ThresholdResolver

# Resolves per-sensor limits from the Neo4j KG (manual-derived ThresholdSpecs),
# falling back to the temporary hardcoded values in zone_definitions.json.
threshold_resolver = ThresholdResolver(ZONE_DEFS_PATH, ZONE_TO_KG)

# Resolved table is mirrored to Redis so other processes (CV pipeline zone
# coloring) threshold-check with the SAME limits as the anomaly detector.
RESOLVED_THRESHOLDS_KEY = "rigvision:thresholds:resolved"

# Per-zone breach signature {zone_id: (severity, sorted triggered sensors)} of the
# last AUTO alert, so a standing breach isn't re-published on every sensor send.
_last_alert_signatures: Dict[str, tuple] = {}

async def publish_resolved_thresholds() -> dict:
    table = await asyncio.to_thread(threshold_resolver.get_table)
    await get_redis().set(RESOLVED_THRESHOLDS_KEY, json.dumps(table))
    return table

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
                "warning_low": s.get("warning_low"),
                "critical_low": s.get("critical_low"),
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
    # Track last seen status per zone so we only auto-diagnose on transitions.
    _last_zone_statuses: Dict[str, str] = {}
    while True:
        try:
            p_raw, z_hash, d_raw, ppe_raw, prog_map = await asyncio.gather(
                r.get("rigvision:persons"),
                r.hgetall("rigvision:zones"),
                r.get("rigvision:diagnostics"),
                r.get("rigvision:ppe:latest"),
                r.hgetall(PROGRESS_KEY),
            )

            # Live diagnosis progress: parse each event's entry and prune stale ones.
            diag_progress, stale_eids = {}, []
            now_ms = int(time.time() * 1000)
            for eid, raw in (prog_map or {}).items():
                try:
                    entry = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    stale_eids.append(eid)
                    continue
                if now_ms - entry.get("updated_at", 0) > PROGRESS_TTL_MS:
                    stale_eids.append(eid)
                else:
                    diag_progress[eid] = entry
            if stale_eids:
                await r.hdel(PROGRESS_KEY, *stale_eids)

            # Reconstruct zone state dictionary from Hash
            zones_now = {zid: json.loads(val) for zid, val in z_hash.items()} if z_hash else {}
            z_raw = json.dumps(zones_now, sort_keys=True) if zones_now else ""

            # Auto-diagnose when any zone newly enters warning/critical.
            # dedup=True means a standing breach (same severity + sensors) is only
            # published once; it re-fires only when the breach signature changes.
            if zones_now:
                new_breach = False
                for zid, zstate in zones_now.items():
                    cur_status = zstate.get("status", "normal")
                    prev_status = _last_zone_statuses.get(zid, "normal")
                    if cur_status in ("warning", "critical") and cur_status != prev_status:
                        new_breach = True
                    _last_zone_statuses[zid] = cur_status
                if new_breach:
                    try:
                        sensors_hash = await r.hgetall(SENSORS_KEY)
                        sensors = {sid: json.loads(val) for sid, val in sensors_hash.items()} if sensors_hash else {}
                        await _evaluate_and_publish(sensors, dedup=True)
                    except Exception as e:
                        logger.warning("Auto-diagnose failed: %s", e)

            if manager.active_connections:
                cur_hash = hash((p_raw, z_raw, d_raw, ppe_raw, json.dumps(diag_progress, sort_keys=True)))
                if cur_hash != _prev_hash:
                    _prev_hash = cur_hash
                    msg = {
                        "type": "realtime_update",
                        "timestamp": time.time(),
                        "persons": json.loads(p_raw) if p_raw else [],
                        "zones": zones_now,
                        "diagnostics": json.loads(d_raw) if d_raw else [],
                        "ppe": json.loads(ppe_raw) if ppe_raw else {},
                        "diag_progress": diag_progress,
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
    try:
        await publish_resolved_thresholds()
    except Exception as e:
        logger.warning("Could not publish resolved thresholds at startup: %s", e)
    
    # Run startup evaluation check of current sensor values in Redis
    try:
        r = get_redis()
        sensors_hash = await r.hgetall(SENSORS_KEY)
        if sensors_hash:
            sensors = {sid: json.loads(val) for sid, val in sensors_hash.items()}
            await _evaluate_and_publish(sensors, dedup=False)
            logger.info("Startup diagnostics check completed.")
    except Exception as e:
        logger.warning("Could not run startup diagnostics: %s", e)

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
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

# ── Auth + rate limiting on mutating endpoints ────────────────────────────
# Optional shared-secret auth: if RIGVISION_API_KEY is set, every mutating
# endpoint requires it via the `X-API-Key` header (or `Authorization: Bearer`).
# If unset, auth is OFF (dev convenience) and we warn once at import.
API_KEY = os.getenv("RIGVISION_API_KEY", "").strip() or None
if API_KEY is None:
    logger.warning("RIGVISION_API_KEY not set — mutating endpoints are UNAUTHENTICATED. "
                   "Set it (and VITE_API_KEY in the frontend) before any shared deployment.")

def require_api_key(
    x_api_key: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """FastAPI dependency: enforce the shared secret when one is configured."""
    if API_KEY is None:
        return
    provided = x_api_key
    if not provided and authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    if provided != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

# Minimum seconds between explicit RUN DIAGNOSTICS calls (debounce LLM spam).
DIAGNOSTICS_MIN_INTERVAL = float(os.getenv("DIAGNOSTICS_MIN_INTERVAL", "2.0"))
_last_diagnostics_run = 0.0
_diagnostics_lock = asyncio.Lock()

async def rate_limit_diagnostics():
    """Reject RUN DIAGNOSTICS calls that arrive faster than DIAGNOSTICS_MIN_INTERVAL."""
    global _last_diagnostics_run
    async with _diagnostics_lock:
        now = time.monotonic()
        wait = DIAGNOSTICS_MIN_INTERVAL - (now - _last_diagnostics_run)
        if wait > 0:
            raise HTTPException(status_code=429, detail=f"Rate limited; retry in {wait:.1f}s")
        _last_diagnostics_run = now

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
    z_hash = await get_redis().hgetall("rigvision:zones")
    return {zid: json.loads(val) for zid, val in z_hash.items()} if z_hash else {}

@app.get("/api/diagnostics")
async def get_diagnostics():
    raw = await get_redis().get("rigvision:diagnostics")
    return json.loads(raw) if raw else []

@app.get("/api/ppe")
async def get_ppe():
    """Current PPE detection status (cv/ppe_demo.py → rigvision:ppe:latest)."""
    raw = await get_redis().get("rigvision:ppe:latest")
    return json.loads(raw) if raw else {}

@app.get("/api/ppe/proof/{item}")
async def get_ppe_proof(item: str):
    """Latest 'missing' proof JPEG for a PPE item (base64 in Redis → image/jpeg)."""
    raw = await get_redis().get(f"rigvision:ppe:proof:{item}")
    if not raw:
        raise HTTPException(status_code=404, detail="No proof frame for this item")
    return Response(content=base64.b64decode(raw), media_type="image/jpeg")


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

@app.post("/api/control/clear_cache", dependencies=[Depends(require_api_key)])
async def post_clear_cache():
    await get_redis().publish("rigvision:commands", "clear_cache")
    return {"status": "ok", "message": "clear_cache command published"}

@app.get("/api/documents/manuals")
async def get_all_manuals():
    """Serves the full RigVision Device Manuals document as plain text."""
    doc_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "knowledge",
        "documents",
        "ONGC_Device_Manuals.txt"
    )
    if not os.path.exists(doc_path):
        raise HTTPException(status_code=404, detail="Manuals document not found")
    try:
        with open(doc_path, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(content=content, media_type="text/plain; charset=utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read manuals: {e}")

@app.post("/api/diagnostics/clear", dependencies=[Depends(require_api_key)])
async def clear_diagnostics():
    global _last_alert_signatures
    _last_alert_signatures.clear()
    
    r = get_redis()
    await r.delete("rigvision:diagnostics")
    
    # Broadcast an immediate WebSocket update so that clients clear their local arrays instantly
    p_raw, z_hash = await asyncio.gather(
        r.get("rigvision:persons"),
        r.hgetall("rigvision:zones")
    )
    zones_now = {zid: json.loads(val) for zid, val in z_hash.items()} if z_hash else {}
    msg = {
        "type": "realtime_update",
        "timestamp": time.time(),
        "persons": json.loads(p_raw) if p_raw else [],
        "zones": zones_now,
        "diagnostics": [],
    }
    await manager.broadcast(json.dumps(msg))
    
    # Re-evaluate current sensor readings so standing breaches are immediately re-published and diagnosed
    try:
        sensors_hash = await r.hgetall(SENSORS_KEY)
        if sensors_hash:
            sensors = {sid: json.loads(val) for sid, val in sensors_hash.items()}
            await _evaluate_and_publish(sensors, dedup=True)
    except Exception as e:
        logger.error("Error running re-evaluation after clear: %s", e)
        
    return {"status": "ok", "message": "Diagnostics backlog cleared successfully"}

async def _evaluate_and_publish(sensors: dict, *, dedup: bool) -> dict:
    """Threshold-check every zone against `sensors` using the cached resolved
    thresholds, and publish one Kafka alert per flagged zone (→ anomaly_listener
    → LLM). Returns a summary dict.

    Thresholds are NOT recomputed here — `threshold_resolver.get_table()` returns
    the table built once at startup. This is just the deterministic compare loop.

    Limits come from the ThresholdResolver: manual-derived device limits first,
    zone environmental (HSE) limits second, zone_definitions.json fallback last.
    Each alert carries a threshold_context explaining which limit fired and why.

    When `dedup` is True (auto-fire on sensor send), a zone is only re-alerted when
    its breach state CHANGES (new breach, or a different severity / set of triggered
    sensors); a zone that clears resets so a future breach re-alerts. When False
    (manual RUN DIAGNOSTICS button), every current breach is published."""
    manifest = _build_sensor_manifest()
    thresholds = await asyncio.to_thread(threshold_resolver.get_table)

    now = int(time.time())
    alerts, flagged_signatures = [], {}
    for zid, zone in manifest["zones"].items():
        telemetry, triggered, threshold_context, sev_rank = {}, [], {}, 0
        for s in zone["sensors"]:
            reading = sensors.get(s["id"])
            if not reading or reading.get("value") is None:
                continue
            val = float(reading["value"])
            telemetry[s["type"]] = val
            result = evaluate_threshold(val, thresholds.get(s["id"], s))
            if result.is_breached:
                triggered.append(s["type"])
                threshold_context[s["type"]] = result.context
                sev_rank = max(sev_rank, result.rank)
        if not triggered:
            if dedup:
                _last_alert_signatures.pop(zid, None)   # cleared → allow re-alert later
            continue
        severity = "CRITICAL" if sev_rank == 2 else "HIGH"
        signature = (severity, tuple(sorted(set(triggered))))
        flagged_signatures[zid] = signature
        if dedup and _last_alert_signatures.get(zid) == signature:
            continue   # same standing breach already alerted — don't spam
        alerts.append({
            "event_id": f"anom_{now}_{zid}",
            "zone_id": ZONE_TO_KG.get(zid, zid),   # KG lookup id
            "rig_zone_id": zid,                     # rig id for display
            "severity": severity,
            "triggered_sensors": sorted(set(triggered)),
            "telemetry_snapshot": telemetry,
            "threshold_context": threshold_context,
            "timestamp": now * 1000,
        })

    if dedup:
        _last_alert_signatures.update(flagged_signatures)

    if not alerts:
        return {"status": "all_clear", "zones_checked": len(manifest["zones"]),
                "flagged": list(flagged_signatures.keys()), "alerts_published": 0}

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

@app.post("/api/diagnostics/run",
          dependencies=[Depends(require_api_key), Depends(rate_limit_diagnostics)])
async def run_diagnostics():
    """On-demand diagnostics (RUN DIAGNOSTICS button): force a check of the current
    sensor snapshot and publish an alert for every flagged zone, regardless of
    whether it was already alerted. Auto-check on sensor send (POST /api/sensors)
    covers the hands-off path; this button is the manual re-trigger."""
    sensors_hash = await get_redis().hgetall(SENSORS_KEY)
    sensors = {sid: json.loads(val) for sid, val in sensors_hash.items()} if sensors_hash else {}
    return await _evaluate_and_publish(sensors, dedup=False)

@app.get("/api/thresholds")
async def get_thresholds():
    """The resolved per-sensor threshold table (which limit governs each sensor,
    where it came from, and why it was selected). For inspection/audit."""
    table = await asyncio.to_thread(threshold_resolver.get_table)
    return {"status": threshold_resolver.status(), "thresholds": table}

@app.post("/api/thresholds/refresh", dependencies=[Depends(require_api_key)])
async def refresh_thresholds():
    """Re-resolve thresholds from the knowledge graph (run after re-seeding Neo4j)
    and re-publish them to Redis for the CV pipeline."""
    await asyncio.to_thread(threshold_resolver.refresh)
    table = await publish_resolved_thresholds()
    return {"status": threshold_resolver.status(), "sensor_count": len(table)}

# ── SCADA protocol simulation ─────────────────────────────────────────────────
# Mirrors the register map (scada/config/register_map.yaml) and MQTT topic config
# so every reading from the Sensor Console goes through the same encode→decode
# round-trip that a real Modbus PLC or MQTT broker would produce.
#
# Modbus (zone_a): value → int16/float32 raw register → decoded eng value
#   Any precision beyond the register resolution is naturally quantised here.
# MQTT (zone_b): value → JSON float (3 dp) → decoded — effectively pass-through.
# Manual (others): pass-through with 4 dp rounding.

_MODBUS_REG: Dict[str, dict] = {
    "temp_a":     {"scale": 0.1,  "offset": 0.0, "dtype": "int16",   "unit": "°C"},
    "vib_a":      {"scale": 0.01, "offset": 0.0, "dtype": "int16",   "unit": "g_rms"},
    "gas_a":      {"scale": 0.1,  "offset": 0.0, "dtype": "int16",   "unit": "ppm"},
    "noise_a":    {"scale": 0.1,  "offset": 0.0, "dtype": "int16",   "unit": "dB"},
    "pressure_a": {"scale": 1.0,  "offset": 0.0, "dtype": "float32", "unit": "bar"},
}

_MQTT_SENSORS: Dict[str, dict] = {
    "temp_b":     {"unit": "°C"},
    "vib_b":      {"unit": "g_rms"},
    "gas_b":      {"unit": "ppm"},
    "noise_b":    {"unit": "dB"},
    "pressure_b": {"unit": "bar"},
}

def _protocol_normalize(sensor_id: str, value: float) -> tuple[float, str, str]:
    """
    Simulate the SCADA encode→decode round-trip for one reading.
    Returns (quantized_value, protocol, unit).
    """
    if sensor_id in _MODBUS_REG:
        reg = _MODBUS_REG[sensor_id]
        scale, offset, dtype = reg["scale"], reg["offset"], reg["dtype"]
        if dtype == "float32":
            # IEEE 754 single-precision round-trip (same as pymodbus would produce)
            quantized = struct.unpack(">f", struct.pack(">f", value))[0]
        else:
            # int16: encode → clamp → decode
            raw = int(round((value - offset) / scale))
            raw = max(-32768, min(32767, raw))
            quantized = round(raw * scale + offset, 6)
        return round(quantized, 4), "modbus", reg["unit"]
    if sensor_id in _MQTT_SENSORS:
        # MQTT JSON payload carries 3 decimal places; scale=1.0, offset=0
        return round(value, 3), "mqtt", _MQTT_SENSORS[sensor_id]["unit"]
    return round(value, 4), "manual", ""


def _pg_write_scada(rows: list) -> None:
    """
    Best-effort synchronous write to the scada_readings TimescaleDB table.
    Called via asyncio.to_thread so it never blocks the event loop.
    Silently skipped if Postgres is unavailable.
    """
    try:
        import psycopg2
        from datetime import datetime, timezone
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            dbname=os.getenv("POSTGRES_DB", "rigvision"),
            user=os.getenv("POSTGRES_USER", "rigvision"),
            password=os.getenv("POSTGRES_PASSWORD", "rigvision_dev_password"),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO scada_readings "
                "  (time, sensor_id, value, unit, quality, protocol, device) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        datetime.fromtimestamp(r["timestamp"], tz=timezone.utc),
                        r["sensor_id"], r["value"], r["unit"],
                        r["quality"],  r["protocol"], r["device"],
                    )
                    for r in rows
                ],
            )
        conn.commit()
        conn.close()
        logger.debug("SCADA DB: wrote %d reading(s)", len(rows))
    except Exception as e:
        logger.debug("SCADA DB write skipped (%s)", e)


# ── Sensor ingestion (the seam) ──────────────────────────────────────────
# Producers (manual dashboard now, MQTT bridge later) write rigvision:sensors:latest.
# The CV pipeline reads it. Swap the producer, the pipeline never changes.

class SensorReadingsRequest(BaseModel):
    readings: Dict[str, float]   # { sensor_id: value }
    source: str = "manual"       # "manual" | "mqtt" | "sim"
    auto_diagnose: bool = True   # auto threshold-check + alert on write

@app.get("/api/sensors/manifest")
async def get_sensor_manifest():
    """Returns the sensor list (grouped by zone) so the dashboard builds sliders
    dynamically. warning/critical/normal_range are overlaid with the RESOLVED
    thresholds (manual-derived via the KG) so slider color bands match exactly
    what the anomaly detector enforces."""
    m = _build_sensor_manifest()
    table = await asyncio.to_thread(threshold_resolver.get_table)
    for zone in m["zones"].values():
        for s in zone["sensors"]:
            t = table.get(s["id"])
            if not t:
                continue
            s["warning"] = t["warning"]
            s["critical"] = t["critical"]
            s["warning_low"] = t.get("warning_low")
            s["critical_low"] = t.get("critical_low")
            if t.get("normal_range") and t["normal_range"][0] is not None:
                s["normal_range"] = t["normal_range"]
            s["threshold_source"] = {
                "level": t["source_level"],
                "manual": t["source_manual"],
                "device": t["device_name"],
                "reason": t["selection_reason"],
            }
    return {"zones": m["zones"]}

@app.get("/api/sensors")
async def get_sensors():
    """Current values of rigvision:sensors:latest (to populate sliders on open)."""
    sensors_hash = await get_redis().hgetall(SENSORS_KEY)
    return {sid: json.loads(val) for sid, val in sensors_hash.items()} if sensors_hash else {}

@app.post("/api/sensors", dependencies=[Depends(require_api_key)])
async def post_sensors(body: SensorReadingsRequest):
    """Validated ingestion with full SCADA pipeline simulation.

    Each reading is routed through _protocol_normalize so the stored value
    is exactly what the real Modbus/MQTT pipeline would produce:
      - zone_a (Modbus): int16/float32 register encode→decode (quantisation applied)
      - zone_b (MQTT):   JSON float 3 dp round-trip
      - others:          pass-through

    Writes flow to:
      1. rigvision:sensors:latest  — live snapshot (frontend Sensor Console)
      2. scada:setpoints           — Modbus sim register bank
      3. rigvision:zones           — 3D dashboard real-time overlay
      4. scada_readings (Postgres) — historical time-series (best-effort)
      5. Kafka anomaly_listener    — threshold evaluation (auto_diagnose=true)
    """
    valid_ids = _build_sensor_manifest()["valid_ids"]
    unknown = [sid for sid in body.readings if sid not in valid_ids]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown sensor IDs: {unknown}")

    r = get_redis()
    sensors_hash = await r.hgetall(SENSORS_KEY)
    current = {sid: json.loads(val) for sid, val in sensors_hash.items()} if sensors_hash else {}

    now = int(time.time())

    # ── 1. Protocol encode→decode simulation ──────────────────────────────
    # normalized maps sensor_id → (quantized_value, protocol, unit)
    normalized: Dict[str, tuple] = {}
    to_hset = {}
    for sid, value in body.readings.items():
        norm_value, protocol, unit = _protocol_normalize(sid, value)
        normalized[sid] = (norm_value, protocol, unit)
        sensor_data = {"value": norm_value, "updated_at": now, "source": protocol}
        current[sid] = sensor_data
        to_hset[sid] = json.dumps(sensor_data)

    # ── 2. Write sensors:latest ───────────────────────────────────────────
    if to_hset:
        await r.hset(SENSORS_KEY, mapping=to_hset)

    # ── 3. Write setpoints (quantized) so Modbus sim stays consistent ─────
    await r.hset("scada:setpoints", mapping={
        sid: str(vals[0]) for sid, vals in normalized.items()
    })

    # ── 4. Merge into rigvision:zones for the 3D dashboard ───────────────
    _SENSOR_FIELD = {
        "temp": "temperature", "vib": "vibration",
        "gas": "gas_h2s", "noise": "noise", "pressure": "pressure",
    }
    # Group updates by zone to avoid multiple round-trips or overwrite races
    zones_to_update = {}
    for sid, (norm_value, protocol, _unit) in normalized.items():
        parts = sid.rsplit("_", 1)
        if len(parts) != 2:
            continue
        prefix, zone_suffix = parts
        zone_id = f"zone_{zone_suffix}"
        field = next((f for key, f in _SENSOR_FIELD.items() if prefix.startswith(key)), None)
        if not field:
            continue
        if zone_id not in zones_to_update:
            zones_to_update[zone_id] = []
        zones_to_update[zone_id].append((field, norm_value, protocol))

    for zone_id, updates in zones_to_update.items():
        zones_raw = await r.hget("rigvision:zones", zone_id)
        zone_data = json.loads(zones_raw) if zones_raw else {
            "status": "normal", "temperature": 25.0, "vibration": 0.0,
            "noise": 40.0, "gas_h2s": 0.0, "pressure": 1.0,
            "person_count": 0, "ppe_violations": [], "updated_at": now,
        }
        for field, norm_value, protocol in updates:
            zone_data[field] = round(norm_value, 3)
            zone_data.setdefault("sensor_sources", {})[field] = protocol
        zone_data["updated_at"] = now
        await r.hset("rigvision:zones", zone_id, json.dumps(zone_data))

    # ── 5. TimescaleDB — fire-and-forget, never blocks the response ───────
    db_rows = [
        {
            "sensor_id": sid,
            "value":     vals[0],
            "unit":      vals[2],
            "quality":   "good",
            "protocol":  vals[1],
            "device":    "sensor-console",
            "timestamp": now,
        }
        for sid, vals in normalized.items()
    ]
    asyncio.create_task(asyncio.to_thread(_pg_write_scada, db_rows))

    # ── 6. Anomaly detection ──────────────────────────────────────────────
    diagnostics = None
    if body.auto_diagnose:
        try:
            diagnostics = await _evaluate_and_publish(current, dedup=True)
        except HTTPException as e:
            diagnostics = {"status": "error", "detail": e.detail}

    return {
        "status": "ok",
        "updated": list(normalized.keys()),
        "normalized": {sid: {"value": v[0], "protocol": v[1]} for sid, v in normalized.items()},
        "count": len(current),
        "diagnostics": diagnostics,
    }

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
