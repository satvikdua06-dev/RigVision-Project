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
                p_raw, z_raw, v_raw, d_raw = await asyncio.gather(
                    r.get("rigvision:persons"),
                    r.get("rigvision:zones"),
                    r.get("rigvision:violations:latest"),
                    r.get("rigvision:diagnostics")
                )
                cur_hash = hash((p_raw, z_raw, v_raw, d_raw))
                if cur_hash != _prev_hash:
                    _prev_hash = cur_hash
                    msg = {
                        "type": "realtime_update",
                        "timestamp": time.time(),
                        "persons": json.loads(p_raw) if p_raw else [],
                        "zones": json.loads(z_raw) if z_raw else {},
                        "violations": json.loads(v_raw) if v_raw else [],
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
            logger.info("Kafka diagnostics/alerts consumer thread started.")
            consumer = KafkaConsumer(
                "rigvision_alerts",
                "rigvision_diagnostics",
                bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
                auto_offset_reset="latest",
                consumer_timeout_ms=1000
            )
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
            
            latest_alert_raw = r.get("rigvision:latest_alert")
            latest_alert = json.loads(latest_alert_raw) if latest_alert_raw else None

            while True:
                records = consumer.poll(timeout_ms=500)
                for tp, messages in records.items():
                    for message in messages:
                        try:
                            payload = message.value.decode("utf-8")
                            topic = message.topic
                            
                            if topic == "rigvision_alerts":
                                latest_alert = json.loads(payload)
                                r.set("rigvision:latest_alert", payload)
                                logger.info("Backend stored latest alert: %s", payload)
                            elif topic == "rigvision_diagnostics":
                                logger.info("Backend received diagnostic: %s", payload)
                                diag = json.loads(payload)
                                
                                if latest_alert:
                                    diag.update({
                                        "event_id": latest_alert.get("event_id"),
                                        "zone_id": latest_alert.get("zone_id"),
                                        "severity": latest_alert.get("severity"),
                                        "triggered_sensors": latest_alert.get("triggered_sensors"),
                                        "telemetry_snapshot": latest_alert.get("telemetry_snapshot"),
                                        "timestamp": latest_alert.get("timestamp") or int(time.time() * 1000)
                                    })
                                else:
                                    diag["timestamp"] = int(time.time() * 1000)
                                
                                raw = r.get("rigvision:diagnostics")
                                diags = json.loads(raw) if raw else []
                                
                                if not any(d.get("event_id") == diag.get("event_id") for d in diags if "event_id" in d and "event_id" in diag):
                                    diags.insert(0, diag)
                                    if len(diags) > 50:
                                        diags = diags[:50]
                                    r.set("rigvision:diagnostics", json.dumps(diags))
                        except Exception as e:
                            logger.error("Error processing message in thread: %s", e)
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
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173"],
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

@app.get("/api/violations")
async def get_violations():
    raw = await get_redis().get("rigvision:violations:latest")
    return json.loads(raw) if raw else []

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

class VlmGatingRequest(BaseModel):
    enabled: bool

@app.post("/api/control/vlm_gating")
async def post_vlm_gating(body: VlmGatingRequest):
    val = "true" if body.enabled else "false"
    await get_redis().set("rigvision:settings:vlm_gating", val)
    return {"status": "ok", "vlm_gating": val}

@app.post("/api/control/clear_cache")
async def post_clear_cache():
    await get_redis().publish("rigvision:commands", "clear_cache")
    return {"status": "ok", "message": "clear_cache command published"}

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
