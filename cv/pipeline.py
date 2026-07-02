"""RigVision-3D — CV Producer Pipeline (Kafka-staged)

Role in the new architecture (Ayan's refactor):

    [cameras] ─ detect_batch ─ update_tracker(per cam) ─ match_cross_camera
             └─► publish "ccm-matches" ──► TriangulationService ──► "3d-locations"
                                                                  └─► location_service.py ─► Redis

This file is the PRODUCER. It captures frames, runs the stateless detector/tracker/
cross-camera utilities, and publishes matched persons (2D) to the Kafka topic
"ccm-matches". Triangulation (separate service) adds 3D positions; location_service
assigns zones + fuses sensors + writes Redis.

Modes:
  demo  — simulated people written DIRECTLY to Redis (no cameras, no Kafka). For
          frontend/diagnostics testing. Sensor values come from the real seam.
  live  — RTSP/USB cameras → ccm-matches (Kafka).
  video — video files → ccm-matches (Kafka).
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import queue
import signal
import sys
import threading
import time
from types import SimpleNamespace
from typing import List, Optional, Tuple

import numpy as np
import redis

os.environ["OPENCV_LOG_LEVEL"] = "OFF"
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zone_state import load_zone_definitions, build_zone_states, read_sensor_readings, read_resolved_thresholds, assign_zone, DEFAULT_PPE

CCM_TOPIC = "ccm-matches"
shutdown_event = threading.Event()


def signal_handler(sig: int, frame: object) -> None:
    shutdown_event.set()


signal.signal(signal.SIGINT, signal_handler)


# ── BoT-SORT config ───────────────────────────────────────────────────────
def default_botsort_args() -> SimpleNamespace:
    return SimpleNamespace(
        track_high_thresh=0.5, track_low_thresh=0.1, new_track_thresh=0.6,
        track_buffer=30, match_thresh=0.8, proximity_thresh=0.5,
        appearance_thresh=0.25, with_reid=False, mot20=False, device="cpu",
        fast_reid_config=None, fast_reid_weights=None,
    )


def make_aruco():
    import cv2
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    params = cv2.aruco.DetectorParameters()
    try:
        detector = cv2.aruco.ArucoDetector(dictionary, params)
    except Exception:
        detector = None
    return detector, dictionary, params


# ── ccm-matches serialization ─────────────────────────────────────────────
def _serialize_track(t: object) -> dict:
    kp = getattr(t, "keypoints", None)
    return {
        "bbox": [float(v) for v in t.bbox],
        "foot_point": [float(t.foot_point[0]), float(t.foot_point[1])],
        "confidence": float(t.confidence),
        "keypoints": kp.tolist() if hasattr(kp, "tolist") else kp,
        "aruco_id": int(t.aruco_id) if getattr(t, "aruco_id", None) is not None else None,
        "aruco_confidence": float(getattr(t, "aruco_confidence", 0.0)),
        "features": None,
    }


def _serialize_matched(mp: object) -> dict:
    best = max(mp.per_camera.values(), key=lambda t: t.confidence)
    return {
        "track_id": int(mp.global_id),
        "posture": getattr(best, "posture", "standing"),
        "recognition_method": getattr(best, "recognition_method", None),
        "frames_seen": int(getattr(best, "frames_seen", 0)),
        "frames_missing": int(getattr(best, "frames_missing", 0)),
        "per_camera": {f"cam_{int(cid)}": _serialize_track(t) for cid, t in mp.per_camera.items()},
    }


# ── Redis frame uploader (for the camera MJPEG feed) ──────────────────────
def create_redis_uploader(redis_client: redis.Redis, upload_queue: queue.Queue) -> threading.Thread:
    import cv2

    def _uploader():
        while not shutdown_event.is_set():
            try:
                item = upload_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                upload_queue.task_done()
                break
            cam_id, frame = item
            try:
                ok, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ok:
                    redis_client.set(f"rigvision:camera:frame:{cam_id}",
                                     base64.b64encode(jpeg.tobytes()).decode('utf-8'), ex=2)
            except Exception as e:
                print(f"Uploader error: {e}")
            finally:
                upload_queue.task_done()

    t = threading.Thread(target=_uploader, daemon=True)
    t.start()
    return t


def _queue_latest_frame(upload_queue: queue.Queue, cam_id: int, frame: np.ndarray) -> None:
    try:
        upload_queue.put_nowait((cam_id, frame))
        return
    except queue.Full:
        pass
    try:
        upload_queue.get_nowait()
        upload_queue.task_done()
    except queue.Empty:
        pass
    try:
        upload_queue.put_nowait((cam_id, frame))
    except queue.Full:
        pass


def annotate_and_enqueue(frame: np.ndarray, cam_id: int, tracks: list, upload_queue: queue.Queue) -> None:
    import cv2
    annotated = frame.copy()
    for t in tracks:
        x1, y1, x2, y2 = map(int, t.bbox)
        color = (0, 200, 255)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        label = f"#{t.track_id}"
        if getattr(t, "aruco_id", None) is not None:
            label += f" (ARUCO {t.aruco_id})"
        cv2.putText(annotated, label, (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    _queue_latest_frame(upload_queue, cam_id, annotated)


def _shutdown_uploader(upload_queue: queue.Queue, uploader_thread: threading.Thread) -> None:
    try:
        upload_queue.put(None, timeout=1.0)
    except queue.Full:
        pass
    uploader_thread.join(timeout=1.0)


def _make_kafka_producer(bootstrap: str):
    from kafka import KafkaProducer
    return KafkaProducer(
        bootstrap_servers=[s.strip() for s in bootstrap.split(",") if s.strip()],
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )


# ── Threaded camera with auto-reconnect ───────────────────────────────────
class ThreadedCamera:
    def __init__(self, source: str) -> None:
        import cv2
        self.source = source
        self.is_usb = False
        try:
            self.cap = cv2.VideoCapture(int(source))
            self.is_usb = True
        except ValueError:
            self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open camera: {source}")
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if self.is_usb:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.ret, self.frame, self.running = False, None, True
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self) -> None:
        import cv2
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.ret, self.frame = ret, frame.copy() if frame is not None else None
            else:
                with self.lock:
                    self.ret = False
                self.cap.release()
                time.sleep(2.0)
                if not self.running:
                    break
                try:
                    self.cap = cv2.VideoCapture(int(self.source) if self.is_usb else self.source)
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception as e:
                    print(f"Reconnect error: {e}")
                time.sleep(1.0)

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        with self.lock:
            return self.ret, self.frame

    def release(self) -> None:
        self.running = False
        self.thread.join(timeout=1.0)
        self.cap.release()


# ── DEMO MODE (direct-to-Redis simulation) ────────────────────────────────
class DemoDataGenerator:
    def __init__(self, zone_definitions_path: str, num_persons: int = 4) -> None:
        self.zone_defs = load_zone_definitions(zone_definitions_path)
        self.num_persons = num_persons
        self.start_time = time.time()
        self.persons = [{
            "id": i + 1,
            "phase_x": np.random.uniform(0, 2 * math.pi),
            "phase_z": np.random.uniform(0, 2 * math.pi),
            "speed_x": np.random.uniform(0.3, 0.7),
            "speed_z": np.random.uniform(0.2, 0.5),
            "has_hardhat": np.random.random() > 0.3,
            "has_vest": np.random.random() > 0.4,
            "has_goggles": np.random.random() > 0.6,
            "posture": "standing",
        } for i in range(num_persons)]

    def generate_persons(self) -> list[dict]:
        t = time.time() - self.start_time
        res = []
        for p in self.persons:
            x = 5.0 + 4.0 * math.sin(p["speed_x"] * t + p["phase_x"])
            z = 2.5 + 1.8 * math.sin(p["speed_z"] * t + p["phase_z"])
            y = 3.05 if p["id"] % 2 == 1 else 0.05
            x, z = max(0.3, min(9.7, x)), max(0.3, min(4.7, z))
            if 4.0 <= x <= 6.0 and not (1.5 <= z <= 3.5):
                z = 1.5 if z < 1.5 else 3.5
            zone = assign_zone((x, y, z), self.zone_defs)
            if np.random.random() < 0.002:
                p["has_hardhat"] = not p["has_hardhat"]
            if np.random.random() < 0.01:
                p["posture"] = np.random.choice(["standing", "sitting", "bending", "lying"], p=[0.7, 0.15, 0.1, 0.05])
            res.append({
                "id": p["id"],
                "x": round(x, 2), "y": round(y, 2), "z": round(z, 2),
                "zone": zone,
                "floor": 1 if (zone and zone.endswith("_f1")) else 0,
                "posture": p["posture"],
                "ppe": {"hardhat": p["has_hardhat"], "vest": p["has_vest"], "goggles": p["has_goggles"]},
                "confidence": round(float(0.85 + np.random.uniform(0, 0.14)), 2),
                "cameras_visible": int(np.random.choice([1, 2], p=[0.4, 0.6])),
            })
        return res


def run_demo_mode(redis_client: redis.Redis, zone_definitions_path: str) -> None:
    print("[*] DEMO mode (simulated people, real sensor feed). Ctrl+C to stop.")
    generator = DemoDataGenerator(zone_definitions_path, num_persons=4)
    zone_defs = load_zone_definitions(zone_definitions_path)
    frame_count = 0
    while not shutdown_event.is_set():
        t_start = time.time()
        persons = generator.generate_persons()
        sensor_readings = read_sensor_readings(redis_client)
        resolved_thresholds = read_resolved_thresholds(redis_client)
        zone_states = build_zone_states(persons, sensor_readings, zone_defs, resolved_thresholds)
        redis_client.set("rigvision:persons", json.dumps(persons))
        redis_client.set("rigvision:zones", json.dumps(zone_states))
        frame_count += 1
        if frame_count % 50 == 0:
            print(f"  [demo] frame={frame_count} persons={len(persons)}")
        time.sleep(max(0, 0.1 - (time.time() - t_start)))


# ── LIVE / VIDEO MODE (Kafka producer) ────────────────────────────────────
def run_producer_mode(
    redis_client: redis.Redis,
    sources: List[str],
    kafka_bootstrap: str,
    mode_name: str,
    confidence: float = 0.5,
    model_path: str = "yolov8l.pt",
    device: Optional[str] = None,
    resize_width: Optional[int] = None,
    max_fps: Optional[float] = None,
    is_video: bool = False,
) -> None:
    import cv2
    from ultralytics import YOLO
    from detection.detector import detect_batch
    from tracking.tracker import update_tracker
    from tracking.cross_camera import match_cross_camera
    from tracking.botsort.bot_sort import BoTSORT

    print(f"[*] {mode_name.upper()} mode — {len(sources)} source(s) → Kafka topic '{CCM_TOPIC}'")

    # Models / detectors (caller owns these in the new stateless API)
    model = YOLO(model_path)
    if device:
        try:
            model.to(device)
        except Exception as e:
            print(f"[warn] could not move model to {device}: {e}")
    aruco_detector, aruco_dict, aruco_params = make_aruco()

    # Open sources
    caps: dict = {}
    if is_video:
        for i, vp in enumerate(sources):
            if not os.path.exists(vp):
                print(f"Video not found: {vp}")
                sys.exit(1)
            cap = cv2.VideoCapture(vp)
            if not cap.isOpened():
                print(f"Cannot open: {vp}")
                sys.exit(1)
            caps[i] = cap
    else:
        for i, src in enumerate(sources):
            caps[i] = ThreadedCamera(src)

    trackers = {i: BoTSORT(default_botsort_args(), frame_rate=30) for i in caps}
    matching_state: dict = {"previous_matches": {}, "aruco_matches": {}, "next_global_id": 100000}

    producer = _make_kafka_producer(kafka_bootstrap)
    upload_queue: queue.Queue = queue.Queue(maxsize=30)
    uploader_thread = create_redis_uploader(redis_client, upload_queue)

    frame_count = 0
    while not shutdown_event.is_set():
        t_start = time.time()

        # 1. Grab a frame per source
        frames: dict = {}
        for cam_id, cap in caps.items():
            if is_video:
                ret, frame = cap.read()
                if not ret:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = cap.read()
            else:
                ret, frame = cap.read()
            if not ret or frame is None:
                continue
            if resize_width:
                h, w = frame.shape[:2]
                frame = cv2.resize(frame, (resize_width, int(resize_width * (h / w))), interpolation=cv2.INTER_LINEAR)
            frames[cam_id] = frame

        if not frames:
            time.sleep(0.02)
            continue

        # 2. Detect (batched) → 3. Track per camera
        source_ids = sorted(frames.keys())
        batch = detect_batch(
            [frames[i] for i in source_ids], model, confidence,
            aruco_detector=aruco_detector, aruco_dictionary=aruco_dict, aruco_parameters=aruco_params,
        )
        per_camera_tracks = {
            cam_id: update_tracker(trackers[cam_id], frames[cam_id], batch[idx])
            for idx, cam_id in enumerate(source_ids)
        }

        # 4. Cross-camera match → 5. Publish ccm-matches (always, even if empty)
        matched = match_cross_camera(per_camera_tracks, matching_state)
        payload = {
            "timestamp": time.time(),
            "matched_persons": [_serialize_matched(mp) for mp in matched],
        }
        try:
            producer.send(CCM_TOPIC, payload)
        except Exception as e:
            print(f"[kafka] publish error: {e}")

        # Annotated frames for the camera feed
        for cam_id, frame in frames.items():
            annotate_and_enqueue(frame, cam_id, per_camera_tracks.get(cam_id, []), upload_queue)

        frame_count += 1
        elapsed = time.time() - t_start
        if frame_count % 30 == 0:
            producer.flush()
            print(f"  [{mode_name}] frame={frame_count} matched={len(matched)} fps={1.0/max(elapsed,1e-3):.1f}")
        if max_fps:
            time.sleep(max(0, (1.0 / max_fps) - elapsed))

    producer.flush()
    _shutdown_uploader(upload_queue, uploader_thread)
    for cap in caps.values():
        cap.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="RigVision-3D CV Producer Pipeline")
    parser.add_argument("--mode", choices=["demo", "live", "video"], default="demo")
    parser.add_argument("--cameras", nargs="+", default=["0"], help="camera indices/RTSP urls (live) or file paths (video)")
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--model", default="yolov8l.pt")
    parser.add_argument("--device", default=None)
    parser.add_argument("--resize-width", type=int, default=None)
    parser.add_argument("--max-fps", type=float, default=None)
    parser.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "localhost"))
    parser.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", "6379")))
    parser.add_argument("--redis-password", default=None)
    parser.add_argument("--kafka", default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
    args = parser.parse_args()

    cv_dir = os.path.dirname(os.path.abspath(__file__))
    zone_definitions_path = os.path.join(os.path.dirname(cv_dir), "cad", "zone_definitions.json")
    redis_password = args.redis_password or os.getenv("REDIS_PASSWORD") or None

    print(f"[*] Connecting to Redis at {args.redis_host}:{args.redis_port}...")
    redis_client = redis.Redis(host=args.redis_host, port=args.redis_port, password=redis_password, decode_responses=True)
    redis_client.ping()
    print("  [OK] Redis connected\n")

    if args.mode == "demo":
        run_demo_mode(redis_client, zone_definitions_path)
    else:
        run_producer_mode(
            redis_client=redis_client, sources=args.cameras, kafka_bootstrap=args.kafka,
            mode_name=args.mode, confidence=args.confidence, model_path=args.model,
            device=args.device, resize_width=args.resize_width, max_fps=args.max_fps,
            is_video=(args.mode == "video"),
        )


if __name__ == "__main__":
    main()
