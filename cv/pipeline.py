"""RigVision-3D — CV Pipeline (single in-process orchestrator)
================================================================

This is the WHOLE computer-vision path in one process. It captures frames, runs the
stateless detector/tracker/cross-camera utilities, triangulates 3D positions, fuses
sensor readings, and writes the dashboard's two Redis keys directly:

    rigvision:persons   (array of tracked people with 3D positions + zone)
    rigvision:zones     (per-zone status: sensor fusion + occupancy/PPE)

WHY ONE PROCESS (and no Kafka)
──────────────────────────────
The detector, tracker, cross-camera matcher, triangulator and zone-builder are all
pure functions. Earlier the pipeline shipped intermediate "matched persons" over two
Kafka topics (ccm-matches -> 3d-locations) to two extra services. Those topics carried
the SAME data in progressively-enriched form — pure plumbing overhead. They are gone:
everything is chained in this loop. (Kafka is still used elsewhere in RigVision, for the
diagnostics alert bus — but that is the backend's concern, not the CV path.)

PER-ZONE-GROUP PROCESSING (the important structural choice)
────────────────────────────────────────────────────────────
The facility is two stacked rooms, each with TWO overlapping cameras:

    zone_a (Room A, floor 0)  ->  cam0 + cam1
    zone_b (Room B, floor 1)  ->  cam2 + cam3

Every tick we process each zone's camera pair INDEPENDENTLY:

    grab the zone's 2 frames
      -> detect_batch        (one batched YOLO call)
      -> update_tracker      (one BoT-SORT tracker per camera, persistent IDs)
      -> match_cross_camera  (fuse the 2 cameras of THIS zone only, via ArUco/epipolar)
      -> triangulate_dlt     (the matched pair -> one 3D point, reprojection-gated)
      -> place into the (already known) room

Because a person's zone is decided by *which camera group saw them*, two unrelated
people (one per room) can never be fused, and we never need a single world frame shared
across all four cameras. Each zone is an independent stereo unit.

MODES
─────
  demo  — simulated people in both rooms, written DIRECTLY to Redis (no cameras, no
          calibration). Sensor values still come from the real seam. For UI/diagnostics
          testing.  ->  python cv/pipeline.py --mode demo
  live  — RTSP/USB cameras.   ->  python cv/pipeline.py --mode live  --cameras <c0> <c1> <c2> <c3>
  video — video files.        ->  python cv/pipeline.py --mode video --cameras a.mp4 b.mp4 c.mp4 d.mp4
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
from typing import Dict, List, Optional, Tuple

import numpy as np
import redis

os.environ["OPENCV_LOG_LEVEL"] = "OFF"
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

# Make sibling modules (zone_state, detection/, tracking/) importable when this file
# is run directly as a script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zone_state import (
    load_zone_definitions, build_zone_states, read_sensor_readings,
    read_resolved_thresholds, assign_zone, DEFAULT_PPE,
)

shutdown_event = threading.Event()


def signal_handler(sig: int, frame: object) -> None:
    shutdown_event.set()


signal.signal(signal.SIGINT, signal_handler)


# ── Layout helpers ─────────────────────────────────────────────────────────────
def derive_zone_groups(zone_defs: dict) -> Dict[str, List[int]]:
    """Read the camera→zone mapping straight from zone_definitions.json.

    Returns {zone_id: [camera_id, ...]} e.g. {"zone_a": [0, 1], "zone_b": [2, 3]}.
    Camera ids are parsed from the "camN" strings, so the layout is data-driven —
    edit the JSON and the pipeline follows.
    """
    groups: Dict[str, List[int]] = {}
    for zid, zdef in zone_defs["zones"].items():
        ids: List[int] = []
        for cam in zdef.get("cameras", []):
            try:
                ids.append(int(str(cam["id"]).replace("cam", "")))
            except (ValueError, KeyError):
                continue
        if ids:
            groups[zid] = sorted(ids)
    return groups


def place_in_zone(pos_local: Tuple[float, float, float], zdef: dict) -> Tuple[float, float, float]:
    """Map a zone-local (master-camera-frame) triangulated point into the room's world
    bounding box, for display only.

    Zone identity is already exact (it's whichever camera group saw the person), so this
    function does NOT decide the zone — it just decides where inside the known room to
    draw the avatar. Without a surveyed world pose for the master camera we can't do an
    exact world transform, so we treat the metric local X/Z as an offset from the room
    corner, clamp into the room's footprint, and pin Y to the room's floor. Replace this
    with a real world transform once the master-camera world pose is calibrated.
    """
    b = zdef["bounds"]
    mn, mx = b["min"], b["max"]
    x = mn["x"] + min(max(pos_local[0], 0.0), mx["x"] - mn["x"])
    z = mn["z"] + min(max(pos_local[2], 0.0), mx["z"] - mn["z"])
    y = mn["y"] + 0.05  # stand on the room floor (floor 0 -> y≈0.05, floor 1 -> y≈3.05)
    return round(x, 2), round(y, 2), round(z, 2)


# ── BoT-SORT config ────────────────────────────────────────────────────────────
def default_botsort_args() -> SimpleNamespace:
    return SimpleNamespace(
        track_high_thresh=0.5, track_low_thresh=0.1, new_track_thresh=0.6,
        track_buffer=30, match_thresh=0.8, proximity_thresh=0.5,
        appearance_thresh=0.25, with_reid=False, mot20=False, device="cpu",
        fast_reid_config=None, fast_reid_weights=None,
    )


def make_aruco():
    """Build the ArUco detector the detector module uses for identity. Owned here
    (the detection functions are stateless and take these as arguments)."""
    import cv2
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    params = cv2.aruco.DetectorParameters()
    try:
        detector = cv2.aruco.ArucoDetector(dictionary, params)
    except Exception:
        detector = None
    return detector, dictionary, params


# ── Redis camera-frame uploader (MJPEG feed for the dashboard) ──────────────────
def create_redis_uploader(redis_client: redis.Redis, upload_queue: queue.Queue) -> threading.Thread:
    """Background thread that JPEG-encodes annotated frames and writes them to
    rigvision:camera:frame:<cam_id> (expiring after 2s) so the dashboard can show a
    live, boxed video feed without blocking the main CV loop."""
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
    """Enqueue a frame, dropping the oldest if the queue is full (we only care about the
    freshest frame for the live feed — never let encoding lag stall the CV loop)."""
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
    """Draw track boxes/IDs on a copy of the frame and hand it to the uploader thread."""
    import cv2
    annotated = frame.copy()
    for t in tracks:
        x1, y1, x2, y2 = map(int, t.bbox)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 200, 255), 2)
        label = f"#{t.track_id}"
        if getattr(t, "aruco_id", None) is not None:
            label += f" (ARUCO {t.aruco_id})"
        cv2.putText(annotated, label, (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)
    _queue_latest_frame(upload_queue, cam_id, annotated)


def _shutdown_uploader(upload_queue: queue.Queue, uploader_thread: threading.Thread) -> None:
    try:
        upload_queue.put(None, timeout=1.0)
    except queue.Full:
        pass
    uploader_thread.join(timeout=1.0)


# ── Threaded camera with auto-reconnect ─────────────────────────────────────────
class ThreadedCamera:
    """Grabs frames in a background thread and always exposes the LATEST one.

    This decouples capture from processing: a slow camera (or a slow YOLO tick) never
    causes frames to pile up — we simply read the most recent frame each tick and drop
    the rest. That keeps end-to-end latency bounded, at the cost of dropping stale frames.
    """
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
                # Lost the stream (phone disconnected): release and retry in 2s.
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


# ── DEMO MODE (direct-to-Redis simulation, no cameras) ──────────────────────────
class DemoDataGenerator:
    """Generates plausible moving people in BOTH rooms so the dashboard/diagnostics can
    be exercised without cameras. Half the people walk Room A (floor 0), half walk
    Room B (floor 1). Footprint matches the new 4×5m stacked layout."""
    def __init__(self, zone_defs: dict, num_persons: int = 4) -> None:
        self.zone_defs = zone_defs
        self.num_persons = num_persons
        self.start_time = time.time()
        self.persons = [{
            "id": i + 1,
            "phase_x": np.random.uniform(0, 2 * math.pi),
            "phase_z": np.random.uniform(0, 2 * math.pi),
            "speed_x": np.random.uniform(0.3, 0.7),
            "speed_z": np.random.uniform(0.2, 0.5),
            "floor": i % 2,  # alternate people between Room A (0) and Room B (1)
            "posture": "standing",
        } for i in range(num_persons)]

    def generate_persons(self) -> list[dict]:
        t = time.time() - self.start_time
        res = []
        for p in self.persons:
            # Wander inside the shared 8×6m footprint (X∈[0,8], Z∈[0,6]).
            x = 4.0 + 3.0 * math.sin(p["speed_x"] * t + p["phase_x"])
            z = 3.0 + 2.2 * math.sin(p["speed_z"] * t + p["phase_z"])
            x, z = max(0.4, min(7.6, x)), max(0.4, min(5.6, z))
            # Y picks the floor: Room A stands at y≈0.05, Room B (stacked +3.4m) at y≈3.45.
            y = 0.05 + 3.4 * p["floor"]
            zone = assign_zone((x, y, z), self.zone_defs)  # bounding-box test -> zone_a/zone_b
            if np.random.random() < 0.01:
                p["posture"] = np.random.choice(["standing", "sitting", "bending", "lying"],
                                                p=[0.7, 0.15, 0.1, 0.05])
            res.append({
                "id": p["id"],
                "x": round(x, 2), "y": round(y, 2), "z": round(z, 2),
                "zone": zone,
                "floor": p["floor"],
                "posture": p["posture"],
                "ppe": {"hardhat": True, "vest": True, "goggles": True},
                "confidence": round(float(0.85 + np.random.uniform(0, 0.14)), 2),
                "cameras_visible": int(np.random.choice([1, 2], p=[0.4, 0.6])),
            })
        return res


def run_demo_mode(redis_client: redis.Redis, zone_defs: dict) -> None:
    print("[*] DEMO mode (simulated people in both rooms, real sensor feed). Ctrl+C to stop.")
    generator = DemoDataGenerator(zone_defs, num_persons=4)
    frame_count = 0
    while not shutdown_event.is_set():
        t_start = time.time()
        persons = generator.generate_persons()
        # Fuse the SAME way live mode does: read the sensor seam + resolved thresholds,
        # build per-zone state, write both Redis keys.
        sensor_readings = read_sensor_readings(redis_client)
        resolved_thresholds = read_resolved_thresholds(redis_client)
        zone_states = build_zone_states(persons, sensor_readings, zone_defs, resolved_thresholds)
        redis_client.set("rigvision:persons", json.dumps(persons))
        redis_client.set("rigvision:zones", json.dumps(zone_states))
        frame_count += 1
        if frame_count % 50 == 0:
            print(f"  [demo] frame={frame_count} persons={len(persons)}")
        time.sleep(max(0, 0.1 - (time.time() - t_start)))  # ~10 Hz


# ── LIVE / VIDEO MODE (per-zone-group, in-process, direct-to-Redis) ─────────────
def _grab_frame(cap, is_video: bool, resize_width: Optional[int]):
    """Read one frame from a source (looping videos), optionally downscaled."""
    import cv2
    if is_video:
        ret, frame = cap.read()
        if not ret:                       # loop the file when it ends
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()
    else:
        ret, frame = cap.read()
    if not ret or frame is None:
        return None
    if resize_width:
        h, w = frame.shape[:2]
        frame = cv2.resize(frame, (resize_width, int(resize_width * (h / w))), interpolation=cv2.INTER_LINEAR)
    return frame


def run_producer_mode(
    redis_client: redis.Redis,
    zone_defs: dict,
    sources: Dict[int, str],
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
    from tracking.triangulation import (
        load_zone_calibrations, triangulate_dlt, compute_reprojection_avg,
    )

    # zone_groups maps each zone to its two camera ids, read from zone_definitions.json.
    zone_groups = derive_zone_groups(zone_defs)
    print(f"[*] PRODUCER mode — zone groups: {zone_groups}")

    # Per-zone stereo calibration. Real .npz configs override the synthetic fallback,
    # so dropping calibrated files into cv/calibration/configs/ upgrades a zone live.
    configs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration", "configs")
    zone_calibs = load_zone_calibrations(zone_groups, configs_dir)
    reproj_threshold = float(os.getenv("REPROJ_THRESHOLD", "15.0"))

    # ONE detector for all cameras (batched), ONE ArUco detector, ONE BoT-SORT tracker
    # PER camera (each camera has its own persistent track-id space).
    model = YOLO(model_path)
    if device:
        try:
            model.to(device)
        except Exception as e:
            print(f"[warn] could not move model to {device}: {e}")
    aruco_detector, aruco_dict, aruco_params = make_aruco()
    trackers = {cam_id: BoTSORT(default_botsort_args(), frame_rate=30)
                for cam_ids in zone_groups.values() for cam_id in cam_ids}

    # ONE shared cross-camera matching state. Safe to share across zones because its
    # keys are (camera_id, track_id) and camera ids are globally unique (0..3), so
    # global ids never collide between rooms.
    matching_state: dict = {"previous_matches": {}, "aruco_matches": {}, "next_global_id": 100000}

    # Open every camera referenced by the zone groups.
    caps: Dict[int, object] = {}
    for cam_id, src in sources.items():
        if is_video:
            if not os.path.exists(src):
                print(f"Video not found: {src}")
                sys.exit(1)
            cap = cv2.VideoCapture(src)
            if not cap.isOpened():
                print(f"Cannot open: {src}")
                sys.exit(1)
            caps[cam_id] = cap
        else:
            caps[cam_id] = ThreadedCamera(src)

    upload_queue: queue.Queue = queue.Queue(maxsize=30)
    uploader_thread = create_redis_uploader(redis_client, upload_queue)

    frame_count = 0
    while not shutdown_event.is_set():
        t_start = time.time()
        persons_all: List[dict] = []

        # ── Process each zone's camera pair INDEPENDENTLY ───────────────────────
        for zone_id, cam_ids in zone_groups.items():
            zdef = zone_defs["zones"][zone_id]
            zone_floor = zdef.get("floor", 0)

            # 1. Grab the latest frame from each of this zone's cameras (one tick).
            frames: Dict[int, np.ndarray] = {}
            for cam_id in cam_ids:
                cap = caps.get(cam_id)
                if cap is None:
                    continue
                f = (_grab_frame(cap, True, resize_width) if is_video
                     else (lambda r: r[1] if r[0] else None)(cap.read()))
                if f is not None:
                    frames[cam_id] = f
            if not frames:
                continue

            # 2. Detect (one batched YOLO call) → 3. track per camera.
            ordered_ids = sorted(frames.keys())
            batch = detect_batch(
                [frames[c] for c in ordered_ids], model, confidence,
                aruco_detector=aruco_detector, aruco_dictionary=aruco_dict, aruco_parameters=aruco_params,
            )
            per_camera_tracks = {
                cam_id: update_tracker(trackers[cam_id], frames[cam_id], batch[idx])
                for idx, cam_id in enumerate(ordered_ids)
            }

            # 4. Fuse ONLY this zone's two cameras (ArUco first, epipolar fallback using
            #    this zone's fundamental matrix). Cross-zone fusion is impossible here
            #    because we never pass another zone's cameras into this call.
            calib = zone_calibs.get(zone_id)
            fundamentals = calib.fundamental if calib else {}
            matched = match_cross_camera(per_camera_tracks, matching_state, fundamentals)

            # 5. Triangulate each matched person from this zone's pair, then place them
            #    in the known room.
            for mp in matched:
                seen = mp.per_camera                      # {cam_id: TrackedPerson}
                pos_world = None
                cams_in_view = sorted(seen.keys())
                if calib is not None and len(cams_in_view) >= 2:
                    a, b = cams_in_view[0], cams_in_view[1]
                    cal_a, cal_b = calib.cameras.get(a), calib.cameras.get(b)
                    if cal_a is not None and cal_b is not None:
                        try:
                            pt_a = seen[a].foot_point
                            pt_b = seen[b].foot_point
                            pos_local = triangulate_dlt(pt_a, pt_b, cal_a.P, cal_b.P)
                            # Reprojection gate: if the two cameras were matched to
                            # different people, the 3D point won't reproject cleanly.
                            err = compute_reprojection_avg(pos_local, cal_a, cal_b, pt_a, pt_b)
                            if err < reproj_threshold:
                                pos_world = place_in_zone(pos_local, zdef)
                        except Exception:
                            pos_world = None

                # Single-camera sightings (or a rejected triangulation) have no metric
                # 3D fix; we still know the room, so we drop the avatar at the room
                # centre so the person is at least counted/visible. (Swap for a
                # ground-plane ray cast once per-camera world poses are calibrated.)
                if pos_world is None:
                    b = zdef["bounds"]; mn, mx = b["min"], b["max"]
                    pos_world = (round((mn["x"] + mx["x"]) / 2, 2),
                                 round(mn["y"] + 0.05, 2),
                                 round((mn["z"] + mx["z"]) / 2, 2))

                best = max(seen.values(), key=lambda tr: tr.confidence)
                persons_all.append({
                    "id": int(mp.global_id),
                    "x": pos_world[0], "y": pos_world[1], "z": pos_world[2],
                    "zone": zone_id,                       # exact: group-derived, not guessed
                    "floor": zone_floor,
                    "posture": getattr(best, "posture", "standing"),
                    "ppe": dict(DEFAULT_PPE),              # PPE detection not yet integrated
                    "confidence": round(float(best.confidence), 2),
                    "cameras_visible": len(seen),
                    "camera_ids": cams_in_view,
                })

            # Annotated frames for the live MJPEG feed.
            for cam_id, frame in frames.items():
                annotate_and_enqueue(frame, cam_id, per_camera_tracks.get(cam_id, []), upload_queue)

        # ── Fuse sensors + occupancy into zone state and publish to Redis ───────
        sensor_readings = read_sensor_readings(redis_client)
        resolved_thresholds = read_resolved_thresholds(redis_client)
        zone_states = build_zone_states(persons_all, sensor_readings, zone_defs, resolved_thresholds)
        try:
            redis_client.set("rigvision:persons", json.dumps(persons_all))
            redis_client.set("rigvision:zones", json.dumps(zone_states))
        except Exception as e:
            print(f"[redis] write error: {e}")

        frame_count += 1
        elapsed = time.time() - t_start
        if frame_count % 30 == 0:
            print(f"  [producer] frame={frame_count} persons={len(persons_all)} fps={1.0/max(elapsed,1e-3):.1f}")
        if max_fps:
            time.sleep(max(0, (1.0 / max_fps) - elapsed))

    _shutdown_uploader(upload_queue, uploader_thread)
    for cap in caps.values():
        cap.release()


# ── Entry point ─────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="RigVision-3D CV Pipeline (single process)")
    parser.add_argument("--mode", choices=["demo", "live", "video"], default="demo")
    parser.add_argument("--cameras", nargs="+", default=None,
                        help="Per-camera sources in cam-id order: cam0 cam1 cam2 cam3. "
                             "Indices/RTSP urls (live) or file paths (video).")
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--model", default="yolov8l.pt")
    parser.add_argument("--device", default=None)
    parser.add_argument("--resize-width", type=int, default=None)
    parser.add_argument("--max-fps", type=float, default=None)
    parser.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "localhost"))
    parser.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", "6379")))
    parser.add_argument("--redis-password", default=None)
    args = parser.parse_args()

    cv_dir = os.path.dirname(os.path.abspath(__file__))
    zone_defs = load_zone_definitions(os.path.join(os.path.dirname(cv_dir), "cad", "zone_definitions.json"))
    redis_password = args.redis_password or os.getenv("REDIS_PASSWORD") or None

    print(f"[*] Connecting to Redis at {args.redis_host}:{args.redis_port}...")
    redis_client = redis.Redis(host=args.redis_host, port=args.redis_port,
                               password=redis_password, decode_responses=True)
    redis_client.ping()
    print("  [OK] Redis connected\n")

    if args.mode == "demo":
        run_demo_mode(redis_client, zone_defs)
        return

    # Map the --cameras list onto camera ids in the order they appear across the zone
    # groups (cam0, cam1, cam2, cam3). Defaults to USB indices 0..3 if not supplied.
    zone_groups = derive_zone_groups(zone_defs)
    ordered_cam_ids = [cid for cam_ids in zone_groups.values() for cid in cam_ids]
    cam_sources = args.cameras if args.cameras else [str(c) for c in ordered_cam_ids]
    if len(cam_sources) != len(ordered_cam_ids):
        print(f"[warn] {len(cam_sources)} sources given for {len(ordered_cam_ids)} cameras "
              f"{ordered_cam_ids}; matching by position.")
    sources = {cid: cam_sources[i] for i, cid in enumerate(ordered_cam_ids) if i < len(cam_sources)}

    run_producer_mode(
        redis_client=redis_client, zone_defs=zone_defs, sources=sources,
        confidence=args.confidence, model_path=args.model, device=args.device,
        resize_width=args.resize_width, max_fps=args.max_fps,
        is_video=(args.mode == "video"),
    )


if __name__ == "__main__":
    main()
