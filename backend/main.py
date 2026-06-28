"""
RigVision-3D — FastAPI Backend
================================

The server that bridges Redis (CV pipeline output) to the browser (3D dashboard).

WHAT IT DOES:
    1. REST API — on-demand endpoints for current state
    2. WebSocket — real-time 10Hz push to the browser

WHY WebSocket INSTEAD OF POLLING?
──────────────────────────────────
REST polling at 10Hz = 10 HTTP requests/second per client.
Each request: TCP handshake + headers + response = ~50ms overhead.

WebSocket: ONE persistent connection, server pushes only when data changes.
For real-time 3D rendering at 60fps, this difference is critical.

ARCHITECTURE:
    Redis ──(10Hz read)──→ FastAPI ──(WebSocket push)──→ Browser
                           │
                           ├── GET /api/health
                           ├── GET /api/zones
                           ├── GET /api/persons
                           └── GET /api/violations

USAGE:
    python main.py
    # or
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Set

import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse


# ─── Redis Connection ───────────────────────────────────────

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Get the async Redis client."""
    global redis_client
    if redis_client is None:
        redis_client = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
        )
    return redis_client


# ─── WebSocket Manager ──────────────────────────────────────

class ConnectionManager:
    """Manages active WebSocket connections.
    
    Handles multiple browser tabs/windows connecting simultaneously.
    When the CV pipeline writes new data to Redis, ALL connected
    clients get the update.
    """

    def __init__(self) -> None:
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)
        print(f"[ws] Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)
        print(f"[ws] Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: str) -> None:
        """Send a message to ALL connected clients."""
        disconnected: List[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)
        
        for conn in disconnected:
            self.active_connections.discard(conn)


manager = ConnectionManager()


# ─── Background Task: Redis → WebSocket Bridge ──────────────

async def redis_to_websocket_bridge() -> None:
    """Reads Redis at ~10Hz and pushes to all WebSocket clients.
    
    This is the core real-time loop. It:
    1. Reads rigvision:persons, rigvision:zones, rigvision:violations:latest from Redis
    2. Packages them into a single JSON message
    3. Broadcasts to all connected browser clients
    
    Runs as a background async task for the lifetime of the server.
    """
    r = await get_redis()
    print("[bridge] Redis->WebSocket bridge started (10Hz)")
    
    while True:
        try:
            if manager.active_connections:
                # Read all three keys from Redis
                persons_raw = await r.get("rigvision:persons")
                zones_raw = await r.get("rigvision:zones")
                violations_raw = await r.get("rigvision:violations:latest")
                
                # Package into a single message
                message = {
                    "type": "realtime_update",
                    "timestamp": time.time(),
                    "persons": json.loads(persons_raw) if persons_raw else [],
                    "zones": json.loads(zones_raw) if zones_raw else {},
                    "violations": json.loads(violations_raw) if violations_raw else [],
                }
                
                await manager.broadcast(json.dumps(message))
            
            # 10Hz = every 100ms
            await asyncio.sleep(0.1)
        
        except aioredis.ConnectionError:
            print("[bridge] Redis connection lost, retrying in 2s...")
            await asyncio.sleep(2)
        except Exception as e:
            print(f"[bridge] Error: {e}")
            await asyncio.sleep(1)


# ─── App Lifecycle ──────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the Redis→WebSocket bridge when the server starts."""
    # Startup
    r = await get_redis()
    await r.ping()
    print(f"[startup] Redis connected at {REDIS_HOST}:{REDIS_PORT}")
    
    # Start bridge as background task
    bridge_task = asyncio.create_task(redis_to_websocket_bridge())
    
    yield
    
    # Shutdown
    bridge_task.cancel()
    if redis_client:
        await redis_client.close()
    print("[shutdown] Cleanup complete")


# ─── FastAPI App ────────────────────────────────────────────

app = FastAPI(
    title="RigVision-3D API",
    description="Real-time 3D Digital Twin Monitoring System for Industrial Drilling Rigs",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow the Vite dev server (port 3000 and 5173) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── REST Endpoints ────────────────────────────────────────

@app.get("/api/health")
async def health_check() -> Dict[str, Any]:
    """Service health check.
    
    Returns server status and Redis connectivity.
    Useful for monitoring and debugging.
    """
    r = await get_redis()
    try:
        await r.ping()
        redis_status = "connected"
    except Exception:
        redis_status = "disconnected"
    
    return {
        "status": "ok",
        "redis": redis_status,
        "websocket_clients": len(manager.active_connections),
        "timestamp": time.time(),
    }


@app.get("/api/persons")
async def get_persons() -> List[Dict]:
    """Get current tracked persons.
    
    Returns the latest person positions from the CV pipeline.
    For real-time updates, use the WebSocket endpoint instead.
    """
    r = await get_redis()
    raw = await r.get("rigvision:persons")
    return json.loads(raw) if raw else []


@app.get("/api/zones")
async def get_zones() -> Dict:
    """Get current zone states.
    
    Returns sensor readings, status, and person counts per zone.
    """
    r = await get_redis()
    raw = await r.get("rigvision:zones")
    return json.loads(raw) if raw else {}


@app.get("/api/violations")
async def get_violations() -> List[Dict]:
    """Get latest compliance violations."""
    r = await get_redis()
    raw = await r.get("rigvision:violations:latest")
    return json.loads(raw) if raw else []


@app.get("/api/video/mjpeg/{camera_id}")
async def get_mjpeg_stream(camera_id: str):
    """MJPEG stream endpoint that retrieves camera frames from Redis."""
    r = await get_redis()
    
    # Check if the camera stream exists/has frames in Redis first
    frame_exists = await r.exists(f"rigvision:camera:frame:{camera_id}")
    if not frame_exists:
        raise HTTPException(status_code=404, detail=f"Camera stream {camera_id} is offline")

    async def frame_generator():
        missing_count = 0
        while True:
            try:
                # Retrieve base64 encoded frame
                jpeg_b64 = await r.get(f"rigvision:camera:frame:{camera_id}")
                if jpeg_b64:
                    missing_count = 0
                    # Decode base64 to raw jpeg bytes
                    jpeg_bytes = base64.b64decode(jpeg_b64)
                    yield (
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n'
                        b'Content-Length: ' + str(len(jpeg_bytes)).encode() + b'\r\n\r\n' +
                        jpeg_bytes + b'\r\n'
                    )
                else:
                    missing_count += 1
                    if missing_count >= 50:  # 50 * 0.04 = 2.0 seconds of no frames
                        print(f"[mjpeg] Camera {camera_id} offline (no frames in Redis for 2s). Closing stream.")
                        break
            except Exception as e:
                print(f"[mjpeg] Error yielding frame for cam {camera_id}: {e}")
                break
            # Run at ~25fps stream pacing
            await asyncio.sleep(0.04)

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


# ─── WebSocket Endpoint ────────────────────────────────────

@app.websocket("/ws/realtime")
async def websocket_realtime(websocket: WebSocket) -> None:
    """Real-time data stream via WebSocket.
    
    The browser connects here and receives JSON messages at ~10Hz:
    {
        "type": "realtime_update",
        "timestamp": 1716969600.123,
        "persons": [...],
        "zones": {...},
        "violations": [...]
    }
    
    The frontend Zustand store processes these messages and updates
    the 3D scene in real-time.
    """
    await manager.connect(websocket)
    try:
        # Keep connection alive — listen for client messages
        # (e.g., ping/pong, future: client-side commands)
        while True:
            data = await websocket.receive_text()
            # Client can send commands like {"type": "ping"}
            if data:
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                except json.JSONDecodeError:
                    pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


# ─── Entry point ────────────────────────────────────────────

if __name__ == "__main__":
    host = os.getenv("BACKEND_HOST", "0.0.0.0")
    port = int(os.getenv("BACKEND_PORT", "8000"))
    
    print(f"[*] Starting RigVision-3D Backend on {host}:{port}")
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=True,
        log_level="info",
    )
