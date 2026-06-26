"""
RigVision-3D — Main CV Pipeline
=================================

The entry point for the computer vision system. Ties together:
  detection → tracking → cross-camera matching → triangulation → Redis

MODES:
    demo  — No cameras needed. Generates fake person movements for testing.
    live  — Real cameras (DroidCam RTSP or USB webcams).
    video — Pre-recorded video files.

USAGE:
    python pipeline.py --mode demo
    python pipeline.py --mode live --cameras 0 1 2
    python pipeline.py --mode live --cameras rtsp://192.168.1.101:4747/video rtsp://192.168.1.102:4747/video
    python pipeline.py --mode video --cameras test_videos/cam_0.mp4 test_videos/cam_1.mp4

DATA FLOW:
    Camera → Undistort → YOLO detect → BoT-SORT track → Cross-camera match
           → Triangulate → Zone assign → Write to Redis ("rigvision:persons")
    
    Simultaneously generates zone states → Write to Redis ("rigvision:zones")
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import sys
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import redis

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Lightweight imports for demo mode (no YOLO/BoT-SORT needed)
from tracking.triangulation import ZoneAssigner


# ─── Graceful shutdown ──────────────────────────────────────

RUNNING = True

def signal_handler(sig: int, frame: object) -> None:
    global RUNNING
    print("\n[!] Shutting down pipeline...")
    RUNNING = False

signal.signal(signal.SIGINT, signal_handler)


# ─── Zone definitions loader ────────────────────────────────

def load_zone_definitions(path: str) -> Dict:
    """Load zone definitions from JSON."""
    with open(path, "r") as f:
        return json.load(f)


# ─── Demo Mode ──────────────────────────────────────────────

class DemoDataGenerator:
    """Generates fake person movements and sensor data for testing.
    
    Creates N persons that walk around the rooms following sinusoidal
    paths. Generates realistic-looking sensor data with occasional
    warnings. No cameras needed.
    
    This lets you test the entire system (backend, frontend, 3D dashboard)
    without any hardware.
    """

    def __init__(self, zone_definitions_path: str, num_persons: int = 4) -> None:
        self.zone_defs = load_zone_definitions(zone_definitions_path)
        self.num_persons = num_persons
        self.start_time = time.time()
        self.zone_assigner = ZoneAssigner(zone_definitions_path)
        
        # Initialize person states with random starting positions
        self.persons: List[Dict] = []
        for i in range(num_persons):
            self.persons.append({
                "id": i + 1,
                "phase_x": np.random.uniform(0, 2 * math.pi),
                "phase_z": np.random.uniform(0, 2 * math.pi),
                "speed_x": np.random.uniform(0.3, 0.7),
                "speed_z": np.random.uniform(0.2, 0.5),
                "has_hardhat": np.random.random() > 0.3,  # 70% wear hard hats
                "has_vest": np.random.random() > 0.4,      # 60% wear vests
                "has_goggles": np.random.random() > 0.6,   # 40% wear goggles
            })

    def generate_persons(self) -> List[Dict]:
        """Generate current person positions using sinusoidal movement.
        
        Each person moves along a unique sinusoidal path through the rooms.
        The math: x(t) = center_x + amplitude * sin(speed * t + phase)
        
        This creates smooth, continuous movement that looks natural.
        """
        t = time.time() - self.start_time
        result = []

        for person in self.persons:
            pid = person["id"]
            
            # Sinusoidal movement across the room
            # X: 0.5 to 9.5 (full room length with padding)
            x = 5.0 + 4.0 * math.sin(person["speed_x"] * t + person["phase_x"])
            # Z: 0.5 to 4.5 (room width with padding)
            z = 2.5 + 1.8 * math.sin(person["speed_z"] * t + person["phase_z"])
            # Y: slightly above floor (foot position)
            y = 0.05
            
            # Clamp to room bounds
            x = max(0.3, min(9.7, x))
            z = max(0.3, min(4.7, z))
            
            # Handle corridor — if in corridor X range (4-6), clamp Z to corridor bounds (1.5-3.5)
            if 4.0 <= x <= 6.0 and not (1.5 <= z <= 3.5):
                # Push person into corridor Z bounds or into a room
                if z < 1.5:
                    z = 1.5
                elif z > 3.5:
                    z = 3.5
            
            zone = self.zone_assigner.assign(x, y, z)
            
            # Randomly toggle PPE sometimes (simulate removing/putting on)
            if np.random.random() < 0.002:  # ~once every 50 seconds at 10Hz
                person["has_hardhat"] = not person["has_hardhat"]
            
            result.append({
                "id": pid,
                "x": round(x, 2),
                "y": round(y, 2),
                "z": round(z, 2),
                "zone": zone,
                "posture": "standing",
                "ppe": {
                    "hardhat": person["has_hardhat"],
                    "vest": person["has_vest"],
                    "goggles": person["has_goggles"],
                },
                "confidence": round(float(0.85 + np.random.uniform(0, 0.14)), 2),
                "cameras_visible": int(np.random.choice([1, 2], p=[0.4, 0.6])),
            })

        return result

    def generate_zone_states(self, persons: List[Dict]) -> Dict:
        """Generate zone states with sensor data and person counts.
        
        Sensor values follow realistic patterns:
        - Base value ± small Gaussian noise (normal operation)
        - Occasional brief spikes (simulated anomalies)
        - Gradual drift over time (simulated equipment degradation)
        """
        t = time.time() - self.start_time
        zone_ids = list(self.zone_defs["zones"].keys())
        
        states = {}
        for zone_id in zone_ids:
            zone_def = self.zone_defs["zones"][zone_id]
            
            # Count persons in this zone
            zone_persons = [p for p in persons if p["zone"] == zone_id]
            person_count = len(zone_persons)
            
            # PPE violations in this zone
            ppe_violations = []
            for p in zone_persons:
                if not p["ppe"]["hardhat"]:
                    ppe_violations.append(f"Person #{p['id']} missing hard hat")
                if not p["ppe"]["vest"]:
                    ppe_violations.append(f"Person #{p['id']} missing vest")
            
            # Generate sensor values with noise
            # Temperature: base 28°C ± 3°C, slight sinusoidal variation
            temp_base = 28.0 + 3.0 * math.sin(0.05 * t)
            temperature = temp_base + np.random.normal(0, 0.5)
            
            # Vibration: base 1.5 g_rms ± 0.5
            vibration = 1.5 + 0.5 * math.sin(0.1 * t) + np.random.normal(0, 0.2)
            vibration = max(0.1, vibration)
            
            # Noise: base 70 dB ± 5
            noise = 70.0 + 5.0 * math.sin(0.08 * t) + np.random.normal(0, 2)
            
            # Gas H2S: base 1.0 ppm, occasional spikes
            gas = 1.0 + 0.5 * abs(math.sin(0.02 * t)) + np.random.normal(0, 0.3)
            gas = max(0.0, gas)
            
            # Occasional warning spike (every ~60 seconds for zone_a)
            if zone_id == "zone_a" and int(t) % 60 > 50:
                temperature += 15.0  # Temperature spike
            
            # Pressure: base 12 bar ± 2
            pressure = 12.0 + 2.0 * math.sin(0.03 * t) + np.random.normal(0, 0.5)
            
            # Determine status from sensor values and thresholds
            status = "normal"
            warning_reason = None
            
            sensors = zone_def.get("sensors", [])
            for sensor in sensors:
                sensor_type = sensor["type"]
                warning_thresh = sensor.get("warning", float('inf'))
                critical_thresh = sensor.get("critical", float('inf'))
                
                # Get the current value for this sensor type
                value_map = {
                    "temperature": temperature,
                    "vibration": vibration,
                    "noise": noise,
                    "gas_h2s": gas,
                    "pressure": pressure,
                }
                value = value_map.get(sensor_type, 0)
                
                if value >= critical_thresh:
                    status = "critical"
                    warning_reason = f"{sensor_type} = {value:.1f} exceeds critical threshold ({critical_thresh})"
                    break
                elif value >= warning_thresh and status != "critical":
                    status = "warning"
                    warning_reason = f"{sensor_type} = {value:.1f} exceeds warning threshold ({warning_thresh})"
            
            # PPE violations also trigger warnings
            if ppe_violations and status == "normal":
                status = "warning"
                warning_reason = f"{len(ppe_violations)} PPE violation(s)"
            
            # Check occupancy
            max_occ = zone_def.get("max_occupancy", 99)
            if person_count > max_occ:
                status = "warning" if status != "critical" else status
                warning_reason = f"Overcrowded: {person_count}/{max_occ} persons"
            
            states[zone_id] = {
                "status": status,
                "warning_reason": warning_reason,
                "temperature": float(round(temperature, 1)),
                "vibration": float(round(vibration, 2)),
                "noise": float(round(noise, 1)),
                "gas_h2s": float(round(gas, 2)),
                "pressure": float(round(pressure, 1)),
                "person_count": person_count,
                "ppe_violations": ppe_violations,
                "updated_at": int(time.time()),
            }
        
        return states


def run_demo_mode(redis_client: redis.Redis, zone_definitions_path: str) -> None:
    """Run the pipeline in demo mode (no cameras, fake data).
    
    Generates sinusoidal person movements and realistic sensor data.
    Writes to Redis at ~10Hz — same as the live pipeline.
    """
    print("[*] Starting DEMO mode")
    print("    Generating fake person movements and sensor data")
    print("    Writing to Redis at ~10Hz")
    print("    Press Ctrl+C to stop\n")
    
    generator = DemoDataGenerator(zone_definitions_path, num_persons=4)
    frame_count = 0
    
    while RUNNING:
        t_start = time.time()
        
        # Generate data
        persons = generator.generate_persons()
        zone_states = generator.generate_zone_states(persons)
        
        # Write to Redis
        redis_client.set("rigvision:persons", json.dumps(persons))
        redis_client.set("rigvision:zones", json.dumps(zone_states))
        
        frame_count += 1
        if frame_count % 50 == 0:  # Log every 5 seconds
            zones_summary = {zid: zs["status"] for zid, zs in zone_states.items()}
            print(f"  [demo] frame={frame_count} persons={len(persons)} zones={zones_summary}")
        
        # Sleep to maintain ~10Hz
        elapsed = time.time() - t_start
        sleep_time = max(0, 0.1 - elapsed)
        time.sleep(sleep_time)
    
    print(f"[OK] Demo stopped after {frame_count} frames")


# ─── Live Mode ──────────────────────────────────────────────

def run_live_mode(
    redis_client: redis.Redis,
    camera_sources: List[str],
    zone_definitions_path: str,
    calibration_dir: str,
    confidence: float = 0.5,
    model_path: str = "yolov8l.pt",
    show_preview: bool = False,
    device: Optional[str] = None,
    gmc: str = "sparseOptFlow",
) -> None:
    """Run the full CV pipeline with real cameras.
    
    This is the production pipeline:
    Camera -> Undistort -> YOLO -> BoT-SORT -> Cross-camera -> Triangulate -> Redis
    """
    # Import heavy CV dependencies only when actually needed
    import cv2
    from detection.detector import PersonDetector
    from tracking.tracker import PersonTracker, TrackedPerson
    from tracking.cross_camera import CrossCameraMapper, MatchedPerson
    from tracking.triangulation import (
        CameraCalibration,
        Triangulator,
        load_calibrations,
    )

    def open_camera(source: str) -> cv2.VideoCapture:
        """Open a camera source (USB index or RTSP URL)."""
        try:
            cam_index = int(source)
            cap = cv2.VideoCapture(cam_index)
        except ValueError:
            cap = cv2.VideoCapture(source)
        
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open camera: {source}")
        
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        print(f"  Opened {source}: {w}x{h} @ {fps:.1f}fps")
        
        return cap

    print(f"[*] Starting LIVE mode with {len(camera_sources)} camera(s)")
    
    # Initialize components
    detector = PersonDetector(model_path=model_path, confidence=confidence, device=device)
    
    # Open cameras
    cameras: Dict[int, cv2.VideoCapture] = {}
    for i, source in enumerate(camera_sources):
        cameras[i] = open_camera(source)
    
    # Load calibrations (if available)
    calibrations = load_calibrations(calibration_dir)
    if calibrations:
        print(f"  Loaded calibrations for cameras: {list(calibrations.keys())}")
    else:
        print("  [WARN] No calibrations found. Using default calibration.")
        for cam_id in cameras:
            calibrations[cam_id] = CameraCalibration.create_default(cam_id)
    
    # Create one BoT-SORT tracker per camera
    trackers: Dict[int, PersonTracker] = {}
    for cam_id in cameras:
        trackers[cam_id] = PersonTracker(camera_id=cam_id, cmc_method=gmc)
    
    # Cross-camera matcher
    mapper = CrossCameraMapper()
    
    # Triangulator
    triangulator = Triangulator(
        calibrations=calibrations,
        zone_definitions_path=zone_definitions_path,
    )
    
    # Zone assigner for generating zone states
    zone_assigner = ZoneAssigner(zone_definitions_path)
    zone_defs = load_zone_definitions(zone_definitions_path)
    
    print("  [OK] All components initialized. Pipeline running...")
    print("  Press Ctrl+C to stop\n")
    
    frame_count = 0
    
    while RUNNING:
        t_start = time.time()
        
        # 1. Grab frames from all cameras
        frames: Dict[int, np.ndarray] = {}
        for cam_id, cap in cameras.items():
            ret, frame = cap.read()
            if ret:
                # Undistort if calibration exists
                if cam_id in calibrations:
                    cal = calibrations[cam_id]
                    frame = cv2.undistort(frame, cal.K, cal.dist_coeffs)
                frames[cam_id] = frame
        
        if not frames:
            continue
        
        # 2. Detect persons in all frames (batched for GPU efficiency)
        frame_list = [frames[cid] for cid in sorted(frames.keys())]
        cam_ids = sorted(frames.keys())
        batch_detections = detector.detect_batch(frame_list)
        
        # 3. Track per-camera with BoT-SORT
        per_camera_tracks: Dict[int, List[TrackedPerson]] = {}
        for i, cam_id in enumerate(cam_ids):
            tracked = trackers[cam_id].update(frames[cam_id], batch_detections[i])
            per_camera_tracks[cam_id] = tracked
        
        # 4. Cross-camera matching
        # Load fundamental matrices if available (from calibration)
        matched_persons = mapper.match(per_camera_tracks)
        
        # 5. Triangulate 3D positions + assign zones
        matched_persons = triangulator.triangulate_all(matched_persons)
        
        # 6. Build persons JSON for Redis
        persons_json = []
        for mp in matched_persons:
            if mp.position_3d is None:
                continue
            
            # Get PPE from the detection with highest confidence
            best_track = max(mp.per_camera.values(), key=lambda t: t.confidence)
            ppe = best_track.ppe or {"hardhat": False, "vest": False, "goggles": False}
            
            persons_json.append({
                "id": mp.global_id,
                "x": round(mp.position_3d[0], 2),
                "y": round(mp.position_3d[1], 2),
                "z": round(mp.position_3d[2], 2),
                "zone": mp.zone or "unknown",
                "posture": "standing",  # RTMPose integration TODO
                "ppe": ppe,
                "confidence": round(best_track.confidence, 2),
                "cameras_visible": len(mp.per_camera),
                "camera_ids": [int(cid) for cid in mp.per_camera.keys()],
            })
        
        # 7. Generate zone states from person data
        zone_states = _generate_zone_states_from_persons(persons_json, zone_defs)
        
        # 8. Write to Redis
        redis_client.set("rigvision:persons", json.dumps(persons_json))
        redis_client.set("rigvision:zones", json.dumps(zone_states))
        
        # Draw bounding boxes + upload to Redis
        import base64
        for cam_id, frame in frames.items():
            annotated_frame = frame.copy()
            if cam_id in per_camera_tracks:
                for track in per_camera_tracks[cam_id]:
                    x1, y1, x2, y2 = [int(v) for v in track.bbox]
                    has_hat = track.ppe and track.ppe.get("hardhat", False)
                    color = (0, 255, 0) if has_hat else (0, 0, 255)
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(annotated_frame, f"#{track.track_id}", (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                                
            # Encode to JPEG and publish to Redis
            try:
                _, jpeg = cv2.imencode('.jpg', annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                jpeg_b64 = base64.b64encode(jpeg.tobytes()).decode('utf-8')
                redis_client.set(f"rigvision:camera:frame:{cam_id}", jpeg_b64)
            except Exception as e:
                print(f"Error streaming frame to Redis: {e}")
                
            if show_preview:
                cv2.imshow(f"Camera {cam_id}", annotated_frame)
                
        if show_preview:
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        
        frame_count += 1
        if frame_count % 30 == 0:  # Log every ~3 seconds
            fps_actual = 1.0 / max(time.time() - t_start, 0.001)
            print(f"  [live] frame={frame_count} persons={len(persons_json)} fps={fps_actual:.1f}")
        
        # Maintain ~10Hz output rate (detection may be faster)
        elapsed = time.time() - t_start
        sleep_time = max(0, 0.1 - elapsed)
        time.sleep(sleep_time)
    
    # Cleanup
    for cap in cameras.values():
        cap.release()
    if show_preview:
        cv2.destroyAllWindows()
    
    print(f"[OK] Live pipeline stopped after {frame_count} frames")


def _generate_zone_states_from_persons(
    persons: List[Dict], zone_defs: Dict
) -> Dict:
    """Generate zone states based on person positions.
    
    In live/video mode, we don't have real sensors yet.
    Zone status is based on PPE violations and occupancy.
    """
    states = {}
    for zone_id, zone_def in zone_defs["zones"].items():
        zone_persons = [p for p in persons if p["zone"] == zone_id]
        person_count = len(zone_persons)
        
        ppe_violations = []
        for p in zone_persons:
            if not p["ppe"]["hardhat"]:
                ppe_violations.append(f"Person #{p['id']} missing hard hat")
            if not p["ppe"]["vest"]:
                ppe_violations.append(f"Person #{p['id']} missing vest")
        
        status = "normal"
        warning_reason = None
        
        if ppe_violations:
            status = "warning"
            warning_reason = f"{len(ppe_violations)} PPE violation(s)"
        
        max_occ = zone_def.get("max_occupancy", 99)
        if person_count > max_occ:
            status = "critical"
            warning_reason = f"Overcrowded: {person_count}/{max_occ} persons"
        
        states[zone_id] = {
            "status": status,
            "warning_reason": warning_reason,
            "temperature": 28.0,  # Placeholder until real sensors
            "vibration": 1.2,
            "noise": 72.0,
            "gas_h2s": 0.5,
            "pressure": 12.0,
            "person_count": person_count,
            "ppe_violations": ppe_violations,
            "updated_at": int(time.time()),
        }
    
    return states


# ─── Main entry point ───────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="RigVision-3D Computer Vision Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline.py --mode demo
  python pipeline.py --mode live --cameras 0 1 2
  python pipeline.py --mode live --cameras rtsp://192.168.1.101:4747/video
  python pipeline.py --mode video --cameras recording_0.mp4 recording_1.mp4
        """
    )
    parser.add_argument("--mode", choices=["demo", "live", "video"], default="demo",
                        help="Pipeline mode (default: demo)")
    parser.add_argument("--cameras", nargs="+", default=["0"],
                        help="Camera sources (indices, RTSP URLs, or video files)")
    parser.add_argument("--confidence", type=float, default=0.5,
                        help="YOLO confidence threshold (default: 0.5)")
    parser.add_argument("--model", default="yolov8l.pt",
                        help="YOLO model path (default: yolov8l.pt)")
    parser.add_argument("--show-preview", action="store_true",
                        help="Show camera preview windows with detections")
    parser.add_argument("--redis-host", default="localhost",
                        help="Redis host (default: localhost)")
    parser.add_argument("--redis-port", type=int, default=6379,
                        help="Redis port (default: 6379)")
    parser.add_argument("--device", default=None,
                        help="Inference device (e.g. 'cuda', 'cpu', '0'). None = auto-detect.")
    parser.add_argument("--gmc", choices=["sparseOptFlow", "none"], default="sparseOptFlow",
                        help="Camera motion compensation method (default: sparseOptFlow). Use 'none' for static cameras to save CPU.")
    
    args = parser.parse_args()
    
    # Resolve paths
    cv_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(cv_dir)
    zone_definitions_path = os.path.join(project_root, "cad", "zone_definitions.json")
    calibration_dir = os.path.join(cv_dir, "calibration", "configs")
    
    # Connect to Redis
    print(f"[*] Connecting to Redis at {args.redis_host}:{args.redis_port}...")
    redis_client = redis.Redis(
        host=args.redis_host,
        port=args.redis_port,
        decode_responses=True,
    )
    redis_client.ping()
    print("  [OK] Redis connected\n")
    
    # Run the selected mode
    if args.mode == "demo":
        run_demo_mode(redis_client, zone_definitions_path)
    
    elif args.mode == "video":
        run_video_mode(
            redis_client=redis_client,
            video_paths=args.cameras,
            zone_definitions_path=zone_definitions_path,
            confidence=args.confidence,
            model_path=args.model,
            show_preview=args.show_preview,
            device=args.device,
            gmc=args.gmc,
        )
    
    elif args.mode == "live":
        run_live_mode(
            redis_client=redis_client,
            camera_sources=args.cameras,
            zone_definitions_path=zone_definitions_path,
            calibration_dir=calibration_dir,
            confidence=args.confidence,
            model_path=args.model,
            show_preview=args.show_preview,
            device=args.device,
            gmc=args.gmc,
        )


# ─── Video Mode ─────────────────────────────────────────────

def run_video_mode(
    redis_client: redis.Redis,
    video_paths: List[str],
    zone_definitions_path: str,
    confidence: float = 0.5,
    model_path: str = "yolov8l.pt",
    show_preview: bool = False,
    device: Optional[str] = None,
    gmc: str = "sparseOptFlow",
) -> None:
    """Run detection + tracking on pre-recorded video files.
    
    NO CAMERA CALIBRATION NEEDED. Uses a simple pixel-to-room mapping:
    - Foot point horizontal position (X in pixels) -> Room X coordinate
    - Foot point vertical position (Y in pixels) -> Room Z coordinate (depth)
    - Bounding box height -> rough distance estimate
    
    Each video is assigned to a zone:
      1 video  -> maps to zone_a (Room A, X: 0-4)
      2 videos -> video 0 = zone_a, video 1 = zone_b
      3 videos -> video 0 = zone_a, video 1 = corridor, video 2 = zone_b
    
    USAGE:
        python pipeline.py --mode video --cameras video1.mp4
        python pipeline.py --mode video --cameras cam0.mp4 cam1.mp4 --show-preview
        python pipeline.py --mode video --cameras cam0.mp4 cam1.mp4 cam2.mp4
    """
    # Import heavy CV dependencies
    import cv2
    from detection.detector import PersonDetector
    from tracking.tracker import PersonTracker
    
    print("[*] Starting VIDEO mode")
    print(f"    Videos: {video_paths}")
    print(f"    Model: {model_path}, Confidence: {confidence}")
    
    # Validate video files exist
    for vp in video_paths:
        if not os.path.exists(vp):
            print(f"  [ERROR] Video not found: {vp}")
            sys.exit(1)
    
    # Load zone definitions to know room dimensions
    zone_defs = load_zone_definitions(zone_definitions_path)
    zone_ids = list(zone_defs["zones"].keys())  # ['zone_a', 'corridor', 'zone_b']
    zone_assigner = ZoneAssigner(zone_definitions_path)
    
    # Map each video to a zone
    # 1 video -> zone_a only
    # 2 videos -> zone_a + zone_b
    # 3 videos -> zone_a + corridor + zone_b
    if len(video_paths) == 1:
        video_zone_map = {0: "zone_a"}
    elif len(video_paths) == 2:
        video_zone_map = {0: "zone_a", 1: "zone_a"}
    else:
        video_zone_map = {i: zone_ids[min(i, len(zone_ids)-1)] for i in range(len(video_paths))}
    
    print(f"    Zone mapping: {video_zone_map}")
    
    # Initialize YOLO detector
    detector = PersonDetector(model_path=model_path, confidence=confidence, device=device)
    
    # Open video files + create trackers
    caps = {}
    trackers = {}
    frame_sizes = {}
    for i, vp in enumerate(video_paths):
        cap = cv2.VideoCapture(vp)
        if not cap.isOpened():
            print(f"  [ERROR] Cannot open: {vp}")
            sys.exit(1)
        
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        print(f"    Video {i}: {vp} ({w}x{h} @ {fps:.0f}fps, {total} frames) -> {video_zone_map[i]}")
        
        caps[i] = cap
        trackers[i] = PersonTracker(camera_id=i, cmc_method=gmc)
        frame_sizes[i] = (w, h)
    
    print("  [OK] All components initialized. Processing videos...")
    print("  Press Ctrl+C to stop\n")
    
    # Precompute zone bounding boxes for pixel-to-room mapping
    zone_bounds = {}
    for zid, zdef in zone_defs["zones"].items():
        b = zdef["bounds"]
        zone_bounds[zid] = {
            "min_x": b["min"]["x"], "max_x": b["max"]["x"],
            "min_z": b["min"]["z"], "max_z": b["max"]["z"],
        }
    
    frame_count = 0
    global_id_offset = {}  # per-video ID offset to avoid collisions
    for i in range(len(video_paths)):
        global_id_offset[i] = i * 100  # video 0: IDs 100+, video 1: IDs 200+, etc.
    
    while RUNNING:
        t_start = time.time()
        
        # 1. Read a frame from each video
        frames = {}
        finished_videos = []
        for vid_id, cap in caps.items():
            ret, frame = cap.read()
            if not ret:
                # Loop the video back to the beginning
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()
                if not ret:
                    finished_videos.append(vid_id)
                    continue
            frames[vid_id] = frame
        
        if not frames:
            print("[*] All videos finished")
            break
        
        # 2. Run YOLO on all frames (batched)
        frame_list = [frames[vid_id] for vid_id in sorted(frames.keys())]
        vid_ids = sorted(frames.keys())
        batch_detections = detector.detect_batch(frame_list)
        
        # 3. Track per-video with BoT-SORT
        all_persons = []
        per_video_tracks = {}
        
        def get_hist(frame, bbox):
            x1, y1, x2, y2 = [int(v) for v in bbox]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0: return None
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [8, 8], [0, 180, 0, 256])
            cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
            return hist
            
        anchor_hists = {}  # track_id -> hist for video 0
        fused_persons_dict = {}  # final_id -> person_dict
        
        for idx, vid_id in enumerate(vid_ids):
            tracked = trackers[vid_id].update(frames[vid_id], batch_detections[idx])
            per_video_tracks[vid_id] = tracked
            
            # 4. Map pixel positions to room coordinates
            zone_id = video_zone_map[vid_id]
            zb = zone_bounds[zone_id]
            fw, fh = frame_sizes[vid_id]
            
            for person in tracked:
                foot_x, foot_y = person.foot_point
                
                # Map foot_x (0..fw) -> zone X range
                # Left edge of frame = zone min_x, right edge = zone max_x
                norm_x = foot_x / fw  # 0.0 to 1.0
                room_x = zb["min_x"] + norm_x * (zb["max_x"] - zb["min_x"])
                
                # Map foot_y (0..fh) -> zone Z range
                # Top of frame = far from camera (max_z), bottom = close (min_z)
                # In perspective, persons at top of frame are further away
                norm_y = foot_y / fh  # 0.0 (top) to 1.0 (bottom)
                room_z = zb["max_z"] - norm_y * (zb["max_z"] - zb["min_z"])
                
                # Y is always floor level
                room_y = 0.05
                
                
                ppe = person.ppe or {"hardhat": False, "vest": False, "goggles": False}
                
                # Cross-camera matching via color histograms
                final_id = person.track_id + global_id_offset[vid_id]
                hist = get_hist(frames[vid_id], person.bbox)
                
                if vid_id == 0:
                    if hist is not None:
                        anchor_hists[final_id] = hist
                else:
                    if hist is not None:
                        best_match = None
                        best_dist = 0.55  # Max Bhattacharyya distance to match (0.55 allows matching under different angles/lighting)
                        for anchor_id, ahist in anchor_hists.items():
                            dist = cv2.compareHist(hist, ahist, cv2.HISTCMP_BHATTACHARYYA)
                            if dist < best_dist:
                                best_dist = dist
                                best_match = anchor_id
                        if best_match is not None:
                            final_id = best_match
                
                if final_id in fused_persons_dict:
                    # Person already seen in an earlier camera (e.g. video 0). 
                    # We just increase the visibility count. We keep the anchor coordinates.
                    fused_persons_dict[final_id]["cameras_visible"] += 1
                    if int(vid_id) not in fused_persons_dict[final_id]["camera_ids"]:
                        fused_persons_dict[final_id]["camera_ids"].append(int(vid_id))
                else:
                    fused_persons_dict[final_id] = {
                        "id": final_id,
                        "x": float(round(room_x, 2)),
                        "y": float(room_y),
                        "z": float(round(room_z, 2)),
                        "zone": zone_id,
                        "posture": "standing",
                        "ppe": ppe,
                        "confidence": float(round(person.confidence, 2)),
                        "cameras_visible": 1,
                        "camera_ids": [int(vid_id)],
                    }
                    
        all_persons = list(fused_persons_dict.values())
        
        # 5. Generate zone states
        zone_states = _generate_zone_states_from_persons(all_persons, zone_defs)
        
        # 6. Write to Redis
        redis_client.set("rigvision:persons", json.dumps(all_persons))
        redis_client.set("rigvision:zones", json.dumps(zone_states))
        
        # Draw bounding boxes + upload to Redis
        import base64
        for vid_id, frame in frames.items():
            annotated_frame = frame.copy()
            if vid_id in per_video_tracks:
                for track in per_video_tracks[vid_id]:
                    x1, y1, x2, y2 = [int(v) for v in track.bbox]
                    has_hat = track.ppe and track.ppe.get("hardhat", False)
                    color = (0, 255, 0) if has_hat else (0, 0, 255)
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                    label = f"#{track.track_id + global_id_offset[vid_id]}"
                    
                    # Show unified ID if matched
                    if vid_id != 0:
                        hist = get_hist(frame, track.bbox)
                        if hist is not None:
                            for anchor_id, ahist in anchor_hists.items():
                                if cv2.compareHist(hist, ahist, cv2.HISTCMP_BHATTACHARYYA) < 0.4:
                                    label = f"#{anchor_id} (fusion)"
                                    break
                                    
                    cv2.putText(annotated_frame, label, (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            
            zone_id = video_zone_map[vid_id]
            cv2.putText(annotated_frame, f"Zone: {zone_id}", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            
            # Encode to JPEG and publish to Redis
            try:
                _, jpeg = cv2.imencode('.jpg', annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                jpeg_b64 = base64.b64encode(jpeg.tobytes()).decode('utf-8')
                redis_client.set(f"rigvision:camera:frame:{vid_id}", jpeg_b64)
            except Exception as e:
                print(f"Error streaming frame to Redis: {e}")
                
            if show_preview:
                cv2.imshow(f"Video {vid_id} - {zone_id}", annotated_frame)
            
        if show_preview:
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("\n[*] Quit by user")
                break
        
        frame_count += 1
        if frame_count % 30 == 0:
            fps_actual = 1.0 / max(time.time() - t_start, 0.001)
            print(f"  [video] frame={frame_count} persons={len(all_persons)} fps={fps_actual:.1f}")
        
        # Maintain ~10Hz output (video plays at processing speed, not real-time)
        elapsed = time.time() - t_start
        sleep_time = max(0, 0.1 - elapsed)
        time.sleep(sleep_time)
    
    # Cleanup
    for cap in caps.values():
        cap.release()
    if show_preview:
        cv2.destroyAllWindows()
    
    print(f"\n[OK] Video pipeline stopped after {frame_count} frames")


if __name__ == "__main__":
    main()

