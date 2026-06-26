# RigVision-3D

> Real-time 3D Digital Twin Monitoring System for Industrial Drilling Rigs

A browser-based interactive dashboard that fuses a 3D rig model with live multi-camera video feeds and IoT sensor data for real-time safety monitoring.

## 🚀 Quick Start (Demo Mode)

**Prerequisites:** Docker, Python 3.11+, Node.js 18+

```bash
# 1. Clone and setup
git clone <repo-url>
cd rigvision-3d
cp .env.example .env

# 2. Start infrastructure
docker compose up -d

# 3. Install dependencies
cd backend && pip install -r requirements.txt
cd ../cv && pip install -r requirements.txt
cd ../frontend && npm install

# 4. Run in 3 separate terminals:
# Terminal 1 — Backend API
cd backend && python main.py

# Terminal 2 — CV Pipeline (demo mode, no cameras needed)
cd cv && python pipeline.py --mode demo

# Terminal 3 — Frontend
cd frontend && npm run dev

# 5. Open http://localhost:3000
```

## 📷 Live Camera Mode

Requires 3 phones with [DroidCam](https://www.dev47apps.com/) installed:

```bash
# Calibrate cameras (one-time setup)
cd cv/calibration
python generate_aruco.py --checkerboard
python calibrate_intrinsic.py --camera rtsp://PHONE_IP:4747/video --output configs/camera_0.json
# Repeat for each camera

# Run live
cd cv && python pipeline.py --mode live --cameras \
  rtsp://PHONE1:4747/video \
  rtsp://PHONE2:4747/video \
  rtsp://PHONE3:4747/video
```

## 🏗️ Architecture

```
Camera/Phone → CV Pipeline → Redis → FastAPI → WebSocket → React + Three.js
Sensors     → MQTT/EMQX   → Redis ↗
```

| Layer | Tech |
|-------|------|
| 3D Rendering | Three.js, @react-three/fiber |
| Frontend | React 18, Zustand |
| Backend | FastAPI, WebSocket |
| CV | YOLOv8, BoT-SORT, OpenCV |
| Sensors | MQTT, EMQX, Kafka |
| Database | PostgreSQL + TimescaleDB |
| Knowledge | Neo4j, ChromaDB, Gemini/Claude |
| Cache | Redis 7 |

## 📂 Project Structure

```
rigvision-3d/
├── cv/          # Computer vision pipeline (detection, tracking, calibration)
├── backend/     # FastAPI server (REST + WebSocket)
├── frontend/    # React + Three.js dashboard
├── sensors/     # Sensor simulation, MQTT, compliance engine
├── knowledge/   # Knowledge graph, RAG pipeline
├── contracts/   # Shared Redis JSON schemas
├── cad/         # Zone definitions
├── infra/       # Database init scripts
└── scripts/     # Utility scripts
```

## 👥 Team

4 B.Tech students from LNMIIT, Jaipur — Summer Internship at RigVision (May–July 2026)

## 📄 License

Internal project — RigVision
