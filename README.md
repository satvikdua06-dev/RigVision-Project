# RigVision-3D
> **Real-time 3D Digital Twin Monitoring System for Industrial Drilling Rigs**

RigVision-3D is an industrial browser-based interactive dashboard designed for real-time safety, environmental, and asset monitoring on drilling rigs. The system fuses a CAD-derived 3D procedural model of the rig with live multi-camera computer vision feeds and IoT sensor data into a unified digital twin.

Developed by a team of 4 B.Tech students from **LNMIIT, Jaipur (Communication and Computer Engineering)** during an 8-week summer engineering internship at **the core organization** (May–July 2026).

---

## 🌟 Core System Pillars

### 1. 3D Digital Twin & Visualization
* **Procedural 3D Model**: Rendered directly in-browser using Three.js, React (@react-three/fiber), and @react-three/drei based on the layout defined in `cad/zone_definitions.json`. Represents a 10m × 5m × 3m rig area consisting of Room A (4x5m), a Corridor (2x2m), and Room B (4x5m).
* **Translucent Bounding Boxes**: Spatial zones dynamically shift colors depending on state: **Green** (Normal), **Amber** (Warning), and **Red** (Critical Violation/Danger).
* **Interactive Controls**: Features three camera view modes:
  * `OrbitControls` (Default free-look camera)
  * `PointerLockControls` (First-person walk-through of the rig)
  * `MapControls` (Orthographic top-down map view)
* Clickable asset models with real-time metadata popups.

### 2. Multi-Camera Computer Vision Pipeline
* **YOLOv8 Object Detection**: Detects persons and PPE items (hard hats, vests, safety goggles) in one feed-forward pass. Optimized for GPU hardware acceleration on an RTX 4070.
* **Persistent Local Tracking**: Uses a native local implementation of `BoT-SORT` (with Kalman filtering and linear sum assignment) to maintain individual person identities per camera view.
* **Cross-Camera Matching**: Re-identifies individuals across different cameras using Hue-Saturation color histograms (Bhattacharyya distance comparison), linking them under a unified global ID.
* **DLT Triangulation**: Converts matching 2D pixel coordinates of person foot points from multiple cameras into precise 3D coordinates relative to the Room A origin.

### 3. IoT Sensor Ingestion & Anomaly Detection
* **Sensor Metrics**: Ingests Temperature (°C), Vibration (g RMS), Noise (dB), Gas Concentration (H₂S ppm), and Pressure (psi).
* **MQTT Transport**: Real-time communication handled by the `EMQX Broker` at ~1Hz.
* **Anomaly Engine**: Scans incoming sensor data against hardcoded safety thresholds and a running statistical baseline (Z-score > 3σ) to flag anomalous events.

### 4. Safety & Compliance Engine
* **Compliance Auditor**: Runs safety audits every 2 seconds matching the current state of zones against YAML rules.
* **Rule Definitions**: Enforces PPE requirements, occupancy limits (e.g., maximum 3 people in Room A), and environmental boundaries.
* **Auditing Logs**: Logs all violations directly to PostgreSQL with matching timestamped frames as evidence.

### 5. Knowledge Graph & RAG Reasoning
* **Neo4j Graph Database**: Maps relationships between `Zones`, `Equipment`, `Sensors`, `FailureModes`, `Symptoms`, and `Procedures`.
* **LLM Assistant**: A retrieval-augmented generation (RAG) pipeline that retrieves Cypher queries from Neo4j and vector indices from ChromaDB to diagnose root causes of failures and suggest procedures via Gemini / Claude.

---

## 🏗️ System Architecture

```
                               ┌──────────────────────────┐
                               │  3x Phone RTSP Cameras   │
                               └─────────────┬────────────┘
                                             │ (DroidCam stream)
                                             ▼
┌──────────────────────┐       ┌──────────────────────────┐
│  IoT Sensors (MQTT)  │       │   YOLOv8 + BoT-SORT CV   │
└──────────┬───────────┘       └─────────────┬────────────┘
           │ (EMQX Broker)                   │ (Triangulation & Color Match)
           ▼                                 ▼
┌─────────────────────────────────────────────────────────┐
│              Redis Cache & Data Contracts               │
│     - rigvision:persons   - rigvision:zones             │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
               ┌──────────────────────────┐
               │    FastAPI Backend       │
               │ (WebSockets & REST API)  │
               └─────────────┬────────────┘
                             │
                             ▼
               ┌──────────────────────────┐
               │  React + Three.js UI     │
               │  (Digital Twin Canvas)   │
               └──────────────────────────┘
```

### Stack Components
* **Frontend**: React 18, Zustand, Vite, TailwindCSS (if configured), Three.js (@react-three/fiber)
* **Backend API**: FastAPI, Uvicorn
* **CV pipeline**: OpenCV, PyTorch, Ultralytics YOLOv8
* **Databases**: PostgreSQL (with TimescaleDB), Neo4j 5.x, ChromaDB
* **Caching & Brokers**: Redis 7, EMQX (MQTT)

---

## 📂 Project Structure

```
RigVision/
├── cv/                  # Computer vision detection, tracking, and camera calibration
│   ├── calibration/     # Checkerboard tools and camera configs
│   ├── detection/       # YOLOv8 Person & PPE detectors
│   ├── tracking/        # BoT-SORT tracker + cross-camera matching & triangulation
│   └── pipeline.py      # Entry point for live, video, and demo modes
├── backend/             # FastAPI REST and WebSockets server
├── frontend/            # React + Three.js digital twin dashboard
├── sensors/             # IoT simulators, EMQX MQTT clients, and Compliance Engine
├── knowledge/           # Neo4j graph schemas, Cypher scripts, and LLM RAG pipelines
├── contracts/           # Shared Redis schemas and data validation contracts
├── cad/                 # zone_definitions.json laying out coordinates and zones
├── infra/               # TimescaleDB and local database init SQL files
└── Makefile             # Command shortcut definitions
```

---

## 📝 Redis Data Contracts

The pipeline writes to three key Redis values:

### 1. `rigvision:persons` (CV -> Redis at ~10Hz)
Stores coordinates of all tracked persons in meters relative to Room A's origin ($Y$ is up).
```json
[
  {
    "id": 1,
    "x": 3.20,
    "y": 0.05,
    "z": 2.50,
    "zone": "zone_a",
    "posture": "standing",
    "ppe": {
      "hardhat": true,
      "vest": false,
      "goggles": false
    },
    "confidence": 0.94,
    "cameras_visible": 2
  }
]
```

### 2. `rigvision:zones` (Sensor Engine -> Redis at ~1Hz)
Combines CV occupant statistics with physical sensor values.
```json
{
  "zone_a": {
    "status": "warning",
    "temperature": 28.3,
    "vibration": 1.2,
    "noise": 72.0,
    "gas_h2s": 0.5,
    "person_count": 2,
    "ppe_violations": ["vest"],
    "updated_at": 1716969600
  }
}
```

### 3. `rigvision:violations:latest` (Compliance Engine -> Redis)
```json
[
  {
    "id": "v-001",
    "rule_id": "PPE-001",
    "zone": "zone_b",
    "severity": "HIGH",
    "message": "Person #3 missing hard hat",
    "person_ids": [3],
    "timestamp": 1716969600
  }
]
```

---

## 🚀 Setup & Execution Guide

### 1. Prerequisites
Ensure you have the following installed on your machine:
* Python 3.11+
* Node.js 18+
* Docker Desktop (Windows)
* Visual Studio Build Tools (with C++ Desktop development for compiling dependencies like `lap` on Windows)

### 2. Infrastructure Setup
Spin up the local services (Postgres, TimescaleDB, Neo4j, Redis, EMQX) using Docker:
```powershell
# In the root project directory:
make up
```
To check if the containers are healthy:
```powershell
docker ps
```

### 3. Python and Node.js Dependencies
Install all package dependencies for the backend, CV pipeline, and frontend dashboard:
```powershell
make install
```

### 4. Running the Dashboard (Demo / Simulation Mode)
You can run the digital twin using simulated demo inputs in three separate terminals:

* **Terminal 1: Start Backend Server**
  ```powershell
  make backend
  ```
* **Terminal 2: Run CV Pipeline in Simulation**
  ```powershell
  make cv-demo
  ```
* **Terminal 3: Run Frontend Dashboard**
  ```powershell
  make frontend
  ```
Open your browser and navigate to **[http://localhost:3000](http://localhost:3000)**.

---

## 📷 Live Mode & Camera Calibration

RigVision-3D uses phone cameras (DroidCam RTSP feeds) for live video inputs.

### 1. Camera Calibration (One-time Intrinsic setup)
To ensure accurate DLT triangulation of coordinates, you must calibrate the distortion parameters of your phone cameras:
1. Generate and print the ArUco calibration checkerboard:
   ```powershell
   cd cv/calibration
   python generate_aruco.py --checkerboard
   ```
2. Run the calibration script pointing to your camera's RTSP feed (place the checkerboard in view of the camera at different distances and orientations):
   ```powershell
   python calibrate_intrinsic.py --camera rtsp://IP_ADDRESS:4747/video --output configs/camera_0.json
   ```
   *Repeat this step for all three cameras.*

### 2. Executing Live Pipeline
Run the CV pipeline with the calibrated camera RTSP URLs:
```powershell
cd cv
python pipeline.py --mode live --cameras rtsp://IP_ADDRESS_0:4747/video rtsp://IP_ADDRESS_1:4747/video rtsp://IP_ADDRESS_2:4747/video
```

### 3. Running Pre-recorded Video Feeds
To run the pipeline using pre-recorded video tracks for validation:
```powershell
cd cv
python pipeline.py --mode video --cameras path/to/vid0.mp4 path/to/vid1.mp4
```
*Note: Video mode automatically leverages your **RTX 4070 GPU** (`device=cuda:0`) for accelerated inference and matches overlapping frames using HSV color histograms.*
*You can override the target device manually using:*
```powershell
python pipeline.py --mode video --cameras path/to/vid0.mp4 --device cpu
```

---

## 🧪 Pipeline Diagnostics

Verify imports and linear sum math calculations by running:
```powershell
cd cv
python -c "from tracking.tracker import PersonTracker; print('PersonTracker import OK')"
```

To run mathematical tests for bounding box IoU and assignment algorithms:
```powershell
python -c "
import numpy as np
from tracking.botsort import matching
class FakeTrack:
    def __init__(self, tlbr): self.tlbr = np.array(tlbr)
a = [FakeTrack([0,0,10,10])]
b = [FakeTrack([5,5,15,15])]
d = matching.iou_distance(a, b)
print(f'IoU Distance: {d[0,0]:.3f} (expected ~0.857)')
cost = np.array([[0.1, 0.9],[0.9, 0.2]])
m, ua, ub = matching.linear_assignment(cost, thresh=0.5)
print(f'Matches: {m}, unmatched_a: {ua}, unmatched_b: {ub}')
"
```
