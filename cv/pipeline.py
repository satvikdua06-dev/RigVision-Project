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
import base64
import json
import math
import os
os.environ["OPENCV_LOG_LEVEL"] = "OFF"  # Suppress internal OpenCV logging and warnings
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"  # Force TCP for RTSP stream stability
import queue
import signal
import sys
import time
import threading
from typing import Dict, List, Optional, Tuple

# Thread-safe clear tracking cache event
clear_tracking_cache_event = threading.Event()

def redis_command_listener(redis_client: redis.Redis) -> None:
    pubsub = redis_client.pubsub()
    try:
        pubsub.subscribe("rigvision:commands")
        print("[commands] Subscribed to Redis channel 'rigvision:commands'")
        while RUNNING:
            message = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if message:
                data = message.get("data")
                if data == "clear_cache":
                    print("[commands] Received clear_cache command from Redis")
                    clear_tracking_cache_event.set()
            time.sleep(0.1)
    except Exception as e:
        print(f"[commands] PubSub listener error: {e}")

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
                "posture": "standing",
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
            
            # Assign odd person IDs to Floor 1, even to Floor 0
            if pid % 2 == 1:
                y = 3.05
            else:
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
            
            # Randomly transition postures (standing is most common)
            if np.random.random() < 0.01:  # ~once every 10 seconds at 10Hz
                person["posture"] = np.random.choice(
                    ["standing", "sitting", "bending", "lying"],
                    p=[0.7, 0.15, 0.1, 0.05]
                )
            
            floor = 1 if (zone and zone.endswith("_f1")) else 0
            
            result.append({
                "id": pid,
                "x": round(x, 2),
                "y": round(y, 2),
                "z": round(z, 2),
                "zone": zone,
                "floor": floor,
                "posture": person["posture"],
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


import threading

class ThreadedCamera:
    """Threaded camera reader that continuously flushes OpenCV's internal frame buffer.
    
    Reads from the stream as fast as frames arrive in a background thread and holds
    only the latest frame. This completely eliminates RTSP/MJPEG stream buffering latency.
    """
    def __init__(self, source: str) -> None:
        import cv2
        self.source = source
        self.is_usb_cam = False
        try:
            cam_index = int(source)
            self.cap = cv2.VideoCapture(cam_index)
            self.is_usb_cam = True
        except ValueError:
            self.cap = cv2.VideoCapture(source)
            
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open camera: {source}")
            
        # Set buffer size to 1 as a hint
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        # Set resolution only for USB webcams to avoid breaking/reconnecting RTSP streams
        if self.is_usb_cam:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        self.ret = False
        self.frame = None
        self.running = True
        self.lock = threading.Lock()
        
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self) -> None:
        import time
        import cv2
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.ret = ret
                    self.frame = frame.copy() if frame is not None else None
            else:
                with self.lock:
                    self.ret = False
                print(f"[WARN] Camera {self.source} disconnected, attempting reconnect...")
                self.cap.release()
                time.sleep(2.0)
                if not self.running:
                    break
                try:
                    if self.is_usb_cam:
                        self.cap = cv2.VideoCapture(int(self.source))
                        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    else:
                        self.cap = cv2.VideoCapture(self.source)
                        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception as e:
                    print(f"[ERROR] Failed to re-initialize camera {self.source}: {e}")
                time.sleep(1.0)

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        with self.lock:
            return self.ret, self.frame

    def get(self, propId: int) -> float:
        return self.cap.get(propId)

    def release(self) -> None:
        self.running = False
        if self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self.cap.release()


def _draw_skeleton(frame: np.ndarray, keypoints: Optional[np.ndarray]) -> None:
    """Draw the 17 keypoint COCO skeleton on the frame."""
    import cv2
    if keypoints is None or len(keypoints) == 0:
        return
        
    # Standard COCO connection pairs
    CONNECTIONS = [
        (5, 6),   # Shoulder line
        (5, 11),  # Left torso side
        (6, 12),  # Right torso side
        (11, 12), # Hip line
        (5, 7), (7, 9),     # Left arm
        (6, 8), (8, 10),    # Right arm
        (11, 13), (13, 15), # Left leg
        (12, 14), (14, 16), # Right leg
        (0, 1), (0, 2), (1, 3), (2, 4) # Face keypoints connection
    ]
    
    # Draw bones in yellow
    for start_idx, end_idx in CONNECTIONS:
        if start_idx < len(keypoints) and end_idx < len(keypoints):
            pt1 = tuple(map(int, keypoints[start_idx]))
            pt2 = tuple(map(int, keypoints[end_idx]))
            # Skip invalid/zero coordinates
            if pt1 != (0, 0) and pt2 != (0, 0):
                cv2.line(frame, pt1, pt2, (0, 255, 255), 2)
                
    # Draw joints in red
    for kp in keypoints:
        pt = tuple(map(int, kp))
        if pt != (0, 0):
            cv2.circle(frame, pt, 4, (0, 0, 255), -1)

def _evict_stale_tracks(
    per_camera_tracks: Dict[int, List[any]],
    local_to_personnel_map: Dict[Tuple[int, int], int],
    local_to_recognition_method: Dict[Tuple[int, int], str],
    global_to_personnel_map: Dict[int, int],
    global_to_recognition_method: Dict[int, str],
    active_global_ids: set,
    mapper: Optional[any],
    frame_count: int
) -> None:
    # 1. Collect currently active (cam_id, track_id) pairs
    active_local_tracks = set()
    for cam_id, tracks in per_camera_tracks.items():
        for track in tracks:
            active_local_tracks.add((cam_id, track.track_id))
            
    # 2. Remove stale entries from local maps
    stale_local_count = 0
    for key in list(local_to_personnel_map.keys()):
        if key not in active_local_tracks:
            local_to_personnel_map.pop(key, None)
            local_to_recognition_method.pop(key, None)
            stale_local_count += 1
            
    # 3. Remove stale entries from global maps
    stale_global_count = 0
    for gid in list(global_to_personnel_map.keys()):
        if gid not in active_global_ids:
            global_to_personnel_map.pop(gid, None)
            global_to_recognition_method.pop(gid, None)
            stale_global_count += 1
            
    # 4. Remove stale entries from mapper.previous_matches
    stale_mapper_count = 0
    if mapper is not None:
        for key in list(mapper.previous_matches.keys()):
            if key not in active_local_tracks:
                mapper.previous_matches.pop(key, None)
                stale_mapper_count += 1
                
    # Log every 100 frames
    if frame_count % 100 == 0:
        total_evicted = stale_local_count + stale_global_count + stale_mapper_count
        if total_evicted > 0:
            print(f"  [cleanup] Evicted {total_evicted} stale track mappings (local: {stale_local_count}, global: {stale_global_count}, mapper: {stale_mapper_count}) at frame {frame_count}")


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
    resize_width: Optional[int] = None,
    max_fps: Optional[float] = None,
    floor_map: Optional[List[int]] = None,
) -> None:
    """Run the full CV pipeline with real cameras.
    
    This is the production pipeline:
    Camera -> Undistort -> YOLO -> BoT-SORT -> Cross-camera -> Triangulate -> Redis
    """
    # Set up floor mapping
    if floor_map is None:
        floor_map = [0] * len(camera_sources)
    else:
        floor_map = floor_map + [0] * max(0, len(camera_sources) - len(floor_map))

    # Import heavy CV dependencies only when actually needed
    import cv2
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
    except Exception:
        try:
            cv2.utils.logging.setLogLevel(0)
        except Exception:
            pass
    from detection.detector import PersonDetector
    from tracking.tracker import PersonTracker, TrackedPerson
    from tracking.cross_camera import CrossCameraMapper, MatchedPerson
    from tracking.triangulation import (
        CameraCalibration,
        Triangulator,
        load_calibrations,
    )

    def open_camera(source: str) -> ThreadedCamera:
        """Open a camera source in a background thread to prevent buffer lag."""
        cap = ThreadedCamera(source)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        print(f"  Opened threaded camera {source}: {w}x{h} @ {fps:.1f}fps")
        
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
    
    # Initialize background queue and thread for Redis uploads
    import threading
    upload_queue = queue.Queue(maxsize=30)
    
    def redis_uploader():
        import base64
        while RUNNING:
            try:
                item = upload_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            
            if item is None:
                upload_queue.task_done()
                break
                
            cam_id, annotated_frame = item
            try:
                _, jpeg = cv2.imencode('.jpg', annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                jpeg_b64 = base64.b64encode(jpeg.tobytes()).decode('utf-8')
                redis_client.set(f"rigvision:camera:frame:{cam_id}", jpeg_b64, ex=2)
            except Exception as e:
                print(f"Error streaming frame to Redis: {e}")
            finally:
                upload_queue.task_done()

    uploader_thread = threading.Thread(target=redis_uploader, daemon=True)
    uploader_thread.start()
    
    # Mappings for persistent recognition
    global_to_personnel_map: Dict[int, int] = {}
    global_to_recognition_method: Dict[int, str] = {}
    local_to_personnel_map: Dict[Tuple[int, int], int] = {}
    local_to_recognition_method: Dict[Tuple[int, int], str] = {}

    frame_count = 0
    vlm_gating_enabled = False
    
    while RUNNING:
        # Thread-safe cache clear check
        if clear_tracking_cache_event.is_set():
            print("[*] Clearing tracking cache (triggered via Redis)...")
            global_to_personnel_map.clear()
            global_to_recognition_method.clear()
            local_to_personnel_map.clear()
            local_to_recognition_method.clear()
            for tracker in trackers.values():
                tracker.reset()
            clear_tracking_cache_event.clear()

        # VLM gating setting check (every 5 frames)
        if frame_count % 5 == 0:
            try:
                vlm_gating_raw = redis_client.get("rigvision:settings:vlm_gating")
                vlm_gating_enabled = (vlm_gating_raw == "true")
            except Exception as e:
                vlm_gating_enabled = False
                print(f"[WARN] Failed to read VLM gating setting from Redis: {e}")

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
                # Resize if specified
                if resize_width:
                    h, w = frame.shape[:2]
                    aspect_ratio = h / w
                    target_height = int(resize_width * aspect_ratio)
                    frame = cv2.resize(frame, (resize_width, target_height), interpolation=cv2.INTER_LINEAR)
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
        matched_persons = triangulator.triangulate_all(matched_persons, floor_map)

        # Update persistent face/QR recognition mappings and propagate across matched cameras
        for mp in matched_persons:
            # Check if any track currently matched has a face_id detected in this frame
            recognized_id = None
            rec_method = None
            for cam_id, track in mp.per_camera.items():
                if getattr(track, "face_id", None) is not None:
                    recognized_id = track.face_id
                    rec_method = track.recognition_method
                    break
            
            if recognized_id is not None:
                # Store globally
                global_to_personnel_map[mp.global_id] = recognized_id
                global_to_recognition_method[mp.global_id] = rec_method
                # Propagate to all camera tracks in this matched group
                for cam_id, track in mp.per_camera.items():
                    local_to_personnel_map[(cam_id, track.track_id)] = recognized_id
                    local_to_recognition_method[(cam_id, track.track_id)] = rec_method
            else:
                # No face/QR recognized in this frame. Check if global_id is already mapped from a previous frame
                if mp.global_id in global_to_personnel_map:
                    # Propagate to any new/current tracks in this matched group
                    pers_id = global_to_personnel_map[mp.global_id]
                    method = global_to_recognition_method[mp.global_id]
                    for cam_id, track in mp.per_camera.items():
                        local_to_personnel_map[(cam_id, track.track_id)] = pers_id
                        local_to_recognition_method[(cam_id, track.track_id)] = method
                else:
                    # Check if any of the local camera tracks were previously mapped
                    for cam_id, track in mp.per_camera.items():
                        if (cam_id, track.track_id) in local_to_personnel_map:
                            pers_id = local_to_personnel_map[(cam_id, track.track_id)]
                            method = local_to_recognition_method[(cam_id, track.track_id)]
                            global_to_personnel_map[mp.global_id] = pers_id
                            global_to_recognition_method[mp.global_id] = method
                            # Propagate to all tracks in this matched group
                            for cid, t in mp.per_camera.items():
                                local_to_personnel_map[(cid, t.track_id)] = pers_id
                                local_to_recognition_method[(cid, t.track_id)] = method
                            break
        
        # 6. Build persons JSON for Redis (de-duplicated by personnel ID)
        fused_persons_dict = {}
        for mp in matched_persons:
            if mp.position_3d is None:
                continue
            
            # Get PPE from the detection with highest confidence
            best_track = max(mp.per_camera.values(), key=lambda t: t.confidence)
            ppe = best_track.ppe or {"hardhat": False, "vest": False, "goggles": False}
            
            person_id = mp.global_id
            rec_method = None
            if mp.global_id in global_to_personnel_map:
                person_id = global_to_personnel_map[mp.global_id]
                rec_method = global_to_recognition_method.get(mp.global_id)
            
            person_dict = {
                "id": person_id,
                "x": round(mp.position_3d[0], 2),
                "y": round(mp.position_3d[1], 2),
                "z": round(mp.position_3d[2], 2),
                "zone": mp.zone or "unknown",
                "floor": 1 if (mp.zone and mp.zone.endswith("_f1")) else 0,
                "posture": getattr(best_track, "posture", "standing"),
                "ppe": ppe,
                "confidence": round(best_track.confidence, 2),
                "cameras_visible": len(mp.per_camera),
                "camera_ids": [int(cid) for cid in mp.per_camera.keys()],
                "recognition_method": rec_method,
            }
            
            if person_id in fused_persons_dict:
                # Merge camera visibility lists
                existing = fused_persons_dict[person_id]
                for cid in person_dict["camera_ids"]:
                    if cid not in existing["camera_ids"]:
                        existing["camera_ids"].append(cid)
                existing["cameras_visible"] = len(existing["camera_ids"])
                # Keep coordinates and posture from track with more visibility or higher confidence
                if person_dict["cameras_visible"] > existing["cameras_visible"] or \
                   (person_dict["cameras_visible"] == existing["cameras_visible"] and person_dict["confidence"] > existing["confidence"]):
                    existing["x"] = person_dict["x"]
                    existing["y"] = person_dict["y"]
                    existing["z"] = person_dict["z"]
                    existing["zone"] = person_dict["zone"]
                    existing["floor"] = person_dict["floor"]
                    existing["posture"] = person_dict["posture"]
                    existing["ppe"] = person_dict["ppe"]
                    existing["confidence"] = person_dict["confidence"]
                    if rec_method:
                        existing["recognition_method"] = rec_method
            else:
                fused_persons_dict[person_id] = person_dict
                
        persons_json = list(fused_persons_dict.values())
        
        # 7. Generate zone states from person data
        zone_states = _generate_zone_states_from_persons(persons_json, zone_defs)
        
        # 8. Write to Redis
        try:
            redis_client.set("rigvision:persons", json.dumps(persons_json))
            redis_client.set("rigvision:zones", json.dumps(zone_states))
        except Exception as e:
            print(f"[WARN] Failed to write telemetry to Redis: {e}")
        
        # Draw bounding boxes + upload to Redis
        for cam_id, frame in frames.items():
            annotated_frame = frame.copy()
            if cam_id in per_camera_tracks:
                for track in per_camera_tracks[cam_id]:
                    x1, y1, x2, y2 = [int(v) for v in track.bbox]
                    has_hat = track.ppe and track.ppe.get("hardhat", False)
                    color = (0, 255, 0) if has_hat else (0, 0, 255)
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                    
                    label = f"#{track.track_id}"
                    if (cam_id, track.track_id) in local_to_personnel_map:
                        pers_id = local_to_personnel_map[(cam_id, track.track_id)]
                        method = local_to_recognition_method.get((cam_id, track.track_id), "face")
                        label = f"#{pers_id} ({method.upper()})"
                        
                    cv2.putText(annotated_frame, label, (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                    _draw_skeleton(annotated_frame, getattr(track, 'keypoints', None))
                                
            # Put annotated frame on the background uploader queue
            try:
                upload_queue.put_nowait((cam_id, annotated_frame))
            except queue.Full:
                try:
                    upload_queue.get_nowait()
                    upload_queue.task_done()
                except queue.Empty:
                    pass
                try:
                    upload_queue.put_nowait((cam_id, annotated_frame))
                except queue.Full:
                    pass
                
            if show_preview:
                cv2.imshow(f"Camera {cam_id}", annotated_frame)
                
        if show_preview:
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        
        # Evict stale tracks to prevent memory leak
        active_global_ids = {mp.global_id for mp in matched_persons}
        _evict_stale_tracks(
            per_camera_tracks=per_camera_tracks,
            local_to_personnel_map=local_to_personnel_map,
            local_to_recognition_method=local_to_recognition_method,
            global_to_personnel_map=global_to_personnel_map,
            global_to_recognition_method=global_to_recognition_method,
            active_global_ids=active_global_ids,
            mapper=mapper,
            frame_count=frame_count
        )
        
        frame_count += 1
        if frame_count % 30 == 0:  # Log every ~3 seconds
            fps_actual = 1.0 / max(time.time() - t_start, 0.001)
            print(f"  [live] frame={frame_count} persons={len(persons_json)} fps={fps_actual:.1f}")
        
        # Maintain max-fps rate limiter if specified
        if max_fps is not None and max_fps > 0:
            elapsed = time.time() - t_start
            sleep_time = max(0, (1.0 / max_fps) - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
    
    # Cleanup
    # Tell the uploader thread to exit
    upload_queue.put(None)
    uploader_thread.join(timeout=1.0)

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
    parser.add_argument("--resize-width", type=int, default=None,
                        help="Resize input frames to this width (maintaining aspect ratio) to increase performance.")
    parser.add_argument("--max-fps", type=float, default=None,
                        help="Maximum FPS for video mode processing. None/unlimited by default.")
    parser.add_argument("--floor-map", nargs="+", type=int, default=None,
                        help="Floor index mapping for each camera (0 or 1). Default is 0 for all.")
    
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
    
    # Start Redis command listener thread
    cmd_thread = threading.Thread(
        target=redis_command_listener,
        args=(redis_client,),
        daemon=True
    )
    cmd_thread.start()
    
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
            resize_width=args.resize_width,
            max_fps=args.max_fps,
            floor_map=args.floor_map,
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
            resize_width=args.resize_width,
            max_fps=args.max_fps,
            floor_map=args.floor_map,
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
    resize_width: Optional[int] = None,
    max_fps: Optional[float] = None,
    floor_map: Optional[List[int]] = None,
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
    # Set up floor mapping
    if floor_map is None:
        floor_map = [0] * len(video_paths)
    else:
        floor_map = floor_map + [0] * max(0, len(video_paths) - len(floor_map))

    if resize_width is None:
        resize_width = 640

    # Import heavy CV dependencies
    import cv2
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
    except Exception:
        try:
            cv2.utils.logging.setLogLevel(0)
        except Exception:
            pass
    from detection.detector import PersonDetector
    from tracking.tracker import PersonTracker
    import threading

    # Initialize background queue and thread for Redis uploads
    upload_queue = queue.Queue(maxsize=30)
    
    def redis_uploader():
        while RUNNING:
            try:
                item = upload_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            
            if item is None:
                upload_queue.task_done()
                break
                
            vid_id, annotated_frame = item
            try:
                _, jpeg = cv2.imencode('.jpg', annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                jpeg_b64 = base64.b64encode(jpeg.tobytes()).decode('utf-8')
                redis_client.set(f"rigvision:camera:frame:{vid_id}", jpeg_b64, ex=2)
            except Exception as e:
                print(f"Error streaming frame to Redis: {e}")
            finally:
                upload_queue.task_done()

    uploader_thread = threading.Thread(target=redis_uploader, daemon=True)
    uploader_thread.start()

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
        
        # Resize dimensions if target width is specified
        if resize_width:
            aspect_ratio = h / w
            h = int(resize_width * aspect_ratio)
            w = resize_width
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
    
    # Mappings for persistent recognition
    global_to_personnel_map: Dict[int, int] = {}
    global_to_recognition_method: Dict[int, str] = {}
    local_to_personnel_map: Dict[Tuple[int, int], int] = {}
    local_to_recognition_method: Dict[Tuple[int, int], str] = {}

    frame_count = 0
    vlm_gating_enabled = False
    global_id_offset = {}  # per-video ID offset to avoid collisions
    for i in range(len(video_paths)):
        global_id_offset[i] = i * 100  # video 0: IDs 100+, video 1: IDs 200+, etc.
    
    while RUNNING:
        # Thread-safe cache clear check
        if clear_tracking_cache_event.is_set():
            print("[*] Clearing tracking cache (triggered via Redis)...")
            global_to_personnel_map.clear()
            global_to_recognition_method.clear()
            local_to_personnel_map.clear()
            local_to_recognition_method.clear()
            for tracker in trackers.values():
                tracker.reset()
            clear_tracking_cache_event.clear()

        # VLM gating setting check (every 5 frames)
        if frame_count % 5 == 0:
            try:
                vlm_gating_raw = redis_client.get("rigvision:settings:vlm_gating")
                vlm_gating_enabled = (vlm_gating_raw == "true")
            except Exception as e:
                vlm_gating_enabled = False
                print(f"[WARN] Failed to read VLM gating setting from Redis: {e}")

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
            # Resize if specified
            if resize_width:
                h, w = frame.shape[:2]
                aspect_ratio = h / w
                target_height = int(resize_width * aspect_ratio)
                frame = cv2.resize(frame, (resize_width, target_height), interpolation=cv2.INTER_LINEAR)
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
        person_matched_info = {}  # (vid_id, track_id) -> (matched_with_anchor, matched_anchor_id, matched_dist)
        
        for idx, vid_id in enumerate(vid_ids):
            tracked = trackers[vid_id].update(frames[vid_id], batch_detections[idx])
            per_video_tracks[vid_id] = tracked
            
            # 4. Map pixel positions to room coordinates
            zone_id = video_zone_map[vid_id]
            if floor_map[vid_id] == 1 and not zone_id.endswith("_f1"):
                zone_id = f"{zone_id}_f1"
            zb = zone_bounds[zone_id]
            fw, fh = frame_sizes[vid_id]
            
            # Update local personnel mapping for this video track if a face is detected
            for person in tracked:
                if getattr(person, "face_id", None) is not None:
                    local_to_personnel_map[(vid_id, person.track_id)] = person.face_id
                    local_to_recognition_method[(vid_id, person.track_id)] = person.recognition_method
                else:
                    # Restore previous local mapping if it exists
                    if (vid_id, person.track_id) in local_to_personnel_map:
                        person.face_id = local_to_personnel_map[(vid_id, person.track_id)]
                        person.recognition_method = local_to_recognition_method[(vid_id, person.track_id)]

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
                
                # Y is calculated based on floor mapping
                room_y = floor_map[vid_id] * 3.0 + 0.05
                
                ppe = person.ppe or {"hardhat": False, "vest": False, "goggles": False}
                
                # Cross-camera matching via color histograms
                final_id = person.track_id + global_id_offset[vid_id]
                hist = get_hist(frames[vid_id], person.bbox)
                
                matched_with_anchor = False
                matched_anchor_id = None
                matched_dist = None
                
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
                            matched_with_anchor = True
                            matched_anchor_id = best_match
                            matched_dist = best_dist
                
                person_matched_info[(vid_id, person.track_id)] = (matched_with_anchor, matched_anchor_id, matched_dist)

                # Update global personnel mapping for this unified/final ID
                if getattr(person, "face_id", None) is not None:
                    global_to_personnel_map[final_id] = person.face_id
                    global_to_recognition_method[final_id] = person.recognition_method
                else:
                    # Restore global mapping if it exists
                    if final_id in global_to_personnel_map:
                        person.face_id = global_to_personnel_map[final_id]
                        person.recognition_method = global_to_recognition_method[final_id]
                        # Propagate back to local tracker for future stability
                        local_to_personnel_map[(vid_id, person.track_id)] = person.face_id
                        local_to_recognition_method[(vid_id, person.track_id)] = person.recognition_method
                
                redis_id = final_id
                rec_method = None
                if final_id in global_to_personnel_map:
                    redis_id = global_to_personnel_map[final_id]
                    rec_method = global_to_recognition_method.get(final_id)
                
                if redis_id in fused_persons_dict:
                    # Person already seen in an earlier camera (e.g. video 0). 
                    # We just increase the visibility count. We keep the anchor coordinates.
                    fused_persons_dict[redis_id]["cameras_visible"] += 1
                    if int(vid_id) not in fused_persons_dict[redis_id]["camera_ids"]:
                        fused_persons_dict[redis_id]["camera_ids"].append(int(vid_id))
                else:
                    fused_persons_dict[redis_id] = {
                        "id": redis_id,
                        "x": float(round(room_x, 2)),
                        "y": float(room_y),
                        "z": float(round(room_z, 2)),
                        "zone": zone_id,
                        "floor": floor_map[vid_id],
                        "posture": getattr(person, "posture", "standing"),
                        "ppe": ppe,
                        "confidence": float(round(person.confidence, 2)),
                        "cameras_visible": 1,
                        "camera_ids": [int(vid_id)],
                        "recognition_method": rec_method,
                    }
                    
        all_persons = list(fused_persons_dict.values())
        
        # Build label cache after all tracking/matching logic has run for this frame
        label_cache: Dict[Tuple[int, int], str] = {}
        for vid_id, tracked in per_video_tracks.items():
            for person in tracked:
                orig_final_id = person.track_id + global_id_offset[vid_id]
                label = f"#{orig_final_id}"
                if (vid_id, person.track_id) in local_to_personnel_map:
                    pers_id = local_to_personnel_map[(vid_id, person.track_id)]
                    method = local_to_recognition_method.get((vid_id, person.track_id), "face")
                    label = f"#{pers_id} ({method.upper()})"
                else:
                    if vid_id != 0:
                        matched_with_anchor, matched_anchor_id, matched_dist = person_matched_info.get(
                            (vid_id, person.track_id), (False, None, None)
                        )
                        if matched_with_anchor and matched_dist is not None and matched_dist < 0.4:
                            anchor_id = matched_anchor_id
                            label = f"#{anchor_id} (fusion)"
                            if anchor_id in global_to_personnel_map:
                                pers_id = global_to_personnel_map[anchor_id]
                                method = global_to_recognition_method.get(anchor_id, "face")
                                label = f"#{pers_id} ({method.upper()})"
                label_cache[(vid_id, person.track_id)] = label
        
        # 5. Generate zone states
        zone_states = _generate_zone_states_from_persons(all_persons, zone_defs)
        
        # 6. Write to Redis
        try:
            redis_client.set("rigvision:persons", json.dumps(all_persons))
            redis_client.set("rigvision:zones", json.dumps(zone_states))
        except Exception as e:
            print(f"[WARN] Failed to write telemetry to Redis: {e}")
        
        # Draw bounding boxes + upload to Redis
        for vid_id, frame in frames.items():
            annotated_frame = frame.copy()
            if vid_id in per_video_tracks:
                for track in per_video_tracks[vid_id]:
                    x1, y1, x2, y2 = [int(v) for v in track.bbox]
                    has_hat = track.ppe and track.ppe.get("hardhat", False)
                    color = (0, 255, 0) if has_hat else (0, 0, 255)
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                    
                    label = label_cache.get((vid_id, track.track_id), f"#{track.track_id + global_id_offset[vid_id]}")
                                        
                    cv2.putText(annotated_frame, label, (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                    _draw_skeleton(annotated_frame, getattr(track, 'keypoints', None))
            
            zone_id = video_zone_map[vid_id]
            cv2.putText(annotated_frame, f"Zone: {zone_id}", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            
            # Put annotated frame on the background uploader queue
            try:
                upload_queue.put_nowait((vid_id, annotated_frame))
            except queue.Full:
                try:
                    upload_queue.get_nowait()
                    upload_queue.task_done()
                except queue.Empty:
                    pass
                try:
                    upload_queue.put_nowait((vid_id, annotated_frame))
                except queue.Full:
                    pass
                
            if show_preview:
                cv2.imshow(f"Video {vid_id} - {zone_id}", annotated_frame)
            
        if show_preview:
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("\n[*] Quit by user")
                break
        
        # Evict stale tracks to prevent memory leak
        active_global_ids = set(fused_persons_dict.keys())
        _evict_stale_tracks(
            per_camera_tracks=per_video_tracks,
            local_to_personnel_map=local_to_personnel_map,
            local_to_recognition_method=local_to_recognition_method,
            global_to_personnel_map=global_to_personnel_map,
            global_to_recognition_method=global_to_recognition_method,
            active_global_ids=active_global_ids,
            mapper=None,
            frame_count=frame_count
        )
        
        frame_count += 1
        if frame_count % 30 == 0:
            fps_actual = 1.0 / max(time.time() - t_start, 0.001)
            print(f"  [video] frame={frame_count} persons={len(all_persons)} fps={fps_actual:.1f}")
        
        # Maintain max-fps rate limiter if specified
        if max_fps is not None and max_fps > 0:
            elapsed = time.time() - t_start
            sleep_time = max(0, (1.0 / max_fps) - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
    
    # Cleanup
    # Tell the uploader thread to exit
    upload_queue.put(None)
    uploader_thread.join(timeout=1.0)

    for cap in caps.values():
        cap.release()
    if show_preview:
        cv2.destroyAllWindows()
    
    print(f"\n[OK] Video pipeline stopped after {frame_count} frames")


if __name__ == "__main__":
    main()

