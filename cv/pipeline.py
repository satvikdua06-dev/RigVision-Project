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
import signal
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

import numpy as np
import redis

os.environ["OPENCV_LOG_LEVEL"] = "OFF"
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

# Make sibling modules (zone_state, detection/, tracking/) importable when this file
# is run directly as a script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env from repo root (two levels up from cv/) so env vars like PPE_CAMERA_IDS
# are available whether the script is run from cv/ or the project root.
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path, override=True)
except ImportError:
    pass

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


def undistort_point(
    pt: Tuple[float, float],
    K: "np.ndarray",
    dist: "np.ndarray",
) -> Tuple[float, float]:
    """Remove lens distortion from a single image point, returning pixel-space coords.

    cv2.undistortPoints with P=K maps distorted pixels → undistorted pixels (same space
    as the projection matrix P = K @ [R|t]), so DLT can be applied directly.
    """
    import cv2, numpy as np_local
    pts = np_local.array([[[pt[0], pt[1]]]], dtype=np_local.float64)  # (1, 1, 2)
    out = cv2.undistortPoints(pts, K, dist, P=K)
    return float(out[0, 0, 0]), float(out[0, 0, 1])


def place_in_zone(pos_local: Tuple[float, float, float], zdef: dict) -> Tuple[float, float, float]:
    """Map a zone-local (master-camera-frame) triangulated point into room world coordinates.

    Cameras are on the short wall (X≈0) looking down the 5m length, but at a diagonal angle
    because both cameras share the same look_at point. The DLT local frame axes therefore
    contain a mix of room X and Z — a simple swap is insufficient. Instead we derive the
    camera's right and forward unit vectors in room space from position/look_at, then project
    pos_local through those vectors to recover true room X and Z.

        room_X = cam0_x + local[0]*right_x + local[2]*fwd_x
        room_Z = cam0_z + local[0]*right_z + local[2]*fwd_z
    """
    import numpy as _np

    b = zdef["bounds"]
    mn, mx = b["min"], b["max"]

    cams = zdef.get("cameras", [])
    if cams:
        c = cams[0]
        cp = c["position"]
        la = c.get("look_at", cp)
        cam_pos = _np.array([cp["x"], cp["y"], cp["z"]], dtype=_np.float64)
        fwd = _np.array([la["x"] - cp["x"], la["y"] - cp["y"], la["z"] - cp["z"]], dtype=_np.float64)
        fwd /= _np.linalg.norm(fwd)
        # Camera X axis (image right) = cross(fwd, world_up), normalised
        world_up = _np.array([0.0, 1.0, 0.0])
        right = _np.cross(fwd, world_up)
        right /= _np.linalg.norm(right)
        world_x = float(cam_pos[0] + pos_local[0] * right[0] + pos_local[2] * fwd[0])
        world_z = float(cam_pos[2] + pos_local[0] * right[2] + pos_local[2] * fwd[2])
    else:
        # Fallback: simple swap (cameras assumed to look straight along X)
        world_x = mn["x"] + pos_local[2]
        world_z = mn["z"] + pos_local[0]

    x = min(max(world_x, mn["x"]), mx["x"])
    z = min(max(world_z, mn["z"]), mx["z"])
    y = mn["y"] + 0.05
    return round(x, 2), round(y, 2), round(z, 2)


# ── BoT-SORT config ────────────────────────────────────────────────────────────
def default_botsort_args() -> SimpleNamespace:
    return SimpleNamespace(
        track_high_thresh=0.35, track_low_thresh=0.1, new_track_thresh=0.6,
        track_buffer=15, match_thresh=0.8, proximity_thresh=0.5,
        appearance_thresh=0.25, with_reid=False, mot20=False, device="cpu",
        fast_reid_config=None, fast_reid_weights=None,
    )


def make_aruco():
    """Build the ArUco detector the detector module uses for identity. Owned here
    (the detection functions are stateless and take these as arguments).

    Tuned away from OpenCV's defaults for small/distant markers — chest badges
    on a person several meters from camera, downscaled to resize_width, are
    often near the decode floor for a 4x4 dictionary. Defaults are conservative
    (built for close-up, well-lit markers) and reject borderline detections
    rather than risk false positives."""
    import cv2
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    params = cv2.aruco.DetectorParameters()
    # Default 0.03 rejects anything under 3% of the scanned crop's perimeter —
    # too strict for a small chest marker in a tight crop. Lower catches more
    # without materially increasing false positives (still gated by the
    # dictionary's error-correction check).
    params.minMarkerPerimeterRate = 0.01
    # Slightly more lenient quad approximation tolerates motion blur / compression
    # artifacts in the marker's edges (default 0.03).
    params.polygonalApproxAccuracyRate = 0.05
    # Wider adaptive-threshold window range handles uneven lighting across the
    # crop better than the default fixed range.
    params.adaptiveThreshWinSizeMin = 3
    params.adaptiveThreshWinSizeMax = 53
    params.adaptiveThreshWinSizeStep = 4
    # Default CORNER_REFINE_NONE leaves marginal/blurred edges unrefined; subpixel
    # refinement recovers some detections that would otherwise fail to decode.
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    try:
        detector = cv2.aruco.ArucoDetector(dictionary, params)
    except Exception:
        detector = None
    return detector, dictionary, params


# ── Phase 3: decoupled MJPEG feed ───────────────────────────────────────────────
# Before Phase 3, JPEG-encoding the annotated frame happened on the main YOLO loop,
# which meant the dashboard's "live" feed only updated as fast as YOLO finished — about
# 8–12 Hz. That made the feed look laggy even when cameras were running at 25 Hz.
#
# Phase 3 splits the MJPEG path off the YOLO clock entirely:
#
#   • LatestTracks holds the most recent tracks per camera (produced by the YOLO loop).
#   • DisplayLoop is one thread per camera that pulls the freshest frame from its
#     ThreadedCamera, overlays the LatestTracks for that camera (which may be a few
#     hundred ms stale — fine for a visual feed), JPEG-encodes, and writes Redis at
#     the camera's native FPS.
#
# The YOLO loop never touches a JPEG anymore — it only swaps in the latest track list.

class LatestTracks:
    """Thread-safe per-camera track snapshot. YOLO loop is the only writer; display
    threads are readers. We swap whole lists rather than mutate in place, so a reader
    always sees a consistent snapshot without holding the lock during draw."""
    def __init__(self) -> None:
        self._tracks: Dict[int, list] = {}
        self._lock = threading.Lock()

    def set(self, cam_id: int, tracks: list) -> None:
        with self._lock:
            self._tracks[cam_id] = tracks

    def get(self, cam_id: int) -> list:
        with self._lock:
            return self._tracks.get(cam_id, [])


class DisplayLoop:
    """One thread per camera. Reads the latest frame from a ThreadedCamera, overlays
    the latest known tracks, JPEG-encodes, and writes to rigvision:camera:frame:<id>.
    Runs at the camera's native rate (capped at target_fps), independent of YOLO.

    Frame de-dupe via the camera's monotonic frame_seq means we don't re-encode the
    same image twice when the camera is briefly idle.
    """
    def __init__(
        self,
        redis_client: redis.Redis,
        cam_id: int,
        cam: ThreadedCamera,
        latest_tracks: LatestTracks,
        target_fps: float = 25.0,
        jpeg_quality: int = 75,
    ) -> None:
        self.redis = redis_client
        self.cam_id = cam_id
        self.cam = cam
        self.tracks = latest_tracks
        self.frame_interval = 1.0 / target_fps
        self.jpeg_quality = jpeg_quality
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self._frames_published = 0

    def start(self) -> "DisplayLoop":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.running = False
        self.thread.join(timeout=1.0)

    def _run(self) -> None:
        import cv2
        key = f"rigvision:camera:frame:{self.cam_id}"
        last_seq = -1
        last_jpeg_b64: Optional[str] = None
        last_pub_t = 0.0
        t_log = time.time()
        while self.running and not shutdown_event.is_set():
            t_start = time.time()
            ret, frame, seq = self.cam.read_with_seq()
            if not ret or frame is None or seq == last_seq:
                # No new frame (camera paused or briefly offline). Re-publish the
                # last known JPEG every 1 s to keep the Redis TTL alive so the
                # MJPEG feed stays visible instead of going dark during a pause.
                if last_jpeg_b64 is not None and time.time() - last_pub_t >= 1.0:
                    try:
                        self.redis.set(key, last_jpeg_b64, ex=3)
                        last_pub_t = time.time()
                    except Exception:
                        pass
                time.sleep(min(0.01, self.frame_interval * 0.5))
                continue
            last_seq = seq

            tracks = self.tracks.get(self.cam_id)
            if tracks:
                annotated = frame.copy()
                fh, fw = annotated.shape[:2]
                for t in tracks:
                    bx1, by1, bx2, by2 = t.bbox
                    bw, bh = bx2 - bx1, by2 - by1
                    # Expand the drawn box by 12% horizontally and 5% vertically.
                    # The YOLO bbox can be tight on a moving person (especially
                    # mid-stride or at an angle), and the DisplayLoop shows the
                    # last YOLO result which may be ~100ms stale at 10fps YOLO.
                    # This is purely cosmetic — foot_point and triangulation still
                    # use the original (unexpanded) track bbox.
                    x1 = max(0,  int(bx1 - 0.12 * bw))
                    y1 = max(0,  int(by1 - 0.05 * bh))
                    x2 = min(fw, int(bx2 + 0.12 * bw))
                    y2 = min(fh, int(by2 + 0.05 * bh))
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 200, 255), 2)
                    label = f"#{t.track_id}"
                    if getattr(t, "aruco_id", None) is not None:
                        label += f" (ARUCO {t.aruco_id})"
                    cv2.putText(annotated, label, (x1, max(0, y1 - 8)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)
            else:
                # No tracks yet (first ticks before YOLO finishes); show the raw frame.
                annotated = frame

            try:
                ok, jpeg = cv2.imencode('.jpg', annotated,
                                        [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
                if ok:
                    encoded = base64.b64encode(jpeg.tobytes()).decode('utf-8')
                    last_jpeg_b64 = encoded
                    last_pub_t = time.time()
                    self.redis.set(key, encoded, ex=2)
                    self._frames_published += 1
            except Exception as e:
                print(f"[display] cam{self.cam_id} encode/redis error: {e}")

            # Heartbeat: log feed FPS every 5s so it's easy to spot capture starvation.
            now = time.time()
            if now - t_log >= 5.0:
                fps = self._frames_published / (now - t_log)
                print(f"  [display] cam{self.cam_id} feed_fps={fps:.1f}")
                self._frames_published = 0
                t_log = now

            # Cap at target_fps so we don't burn CPU during high-FPS sources.
            sleep = self.frame_interval - (time.time() - t_start)
            if sleep > 0:
                time.sleep(sleep)


# ── Threaded camera with auto-reconnect ─────────────────────────────────────────
class ThreadedCamera:
    """Grabs frames in a background thread and always exposes the LATEST one.

    Capture decoupled from processing: a slow YOLO tick (or any slow consumer) never
    causes frames to pile up — every reader gets the most recent frame and drops the
    rest. End-to-end latency stays bounded, at the cost of dropping stale frames.

    Handles three source kinds uniformly:
      • USB index    (--cameras 0 1 ...)
      • RTSP / URL   (--cameras rtsp://...)
      • Video file   (--mode video, --cameras a.mp4 b.mp4 ...)

    Video files are special: we throttle the reader to the file's native FPS (otherwise
    they'd play at thousands of frames/sec) and loop on EOF, so the dashboard sees a
    continuous "live-like" stream regardless of how often the YOLO loop samples it.
    Live sources reconnect after a disconnect; video sources just seek to frame 0.
    """
    def __init__(self, source: str, *, is_video: bool = False, resize_width: Optional[int] = None,
                 start_frame: int = 0,
                 pause_event: Optional[threading.Event] = None) -> None:
        import cv2
        self.source = source
        self.is_video = is_video
        self.is_usb = False
        self.resize_width = resize_width
        self._start_frame = start_frame
        self._pause_event = pause_event

        if is_video:
            self.cap = cv2.VideoCapture(source)
        else:
            try:
                self.cap = cv2.VideoCapture(int(source))
                self.is_usb = True
            except ValueError:
                self.cap = cv2.VideoCapture(source)

        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open camera/source: {source}")

        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if self.is_usb:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        if is_video and start_frame > 0:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        # Pace video files at their native FPS so the simulated stream behaves like
        # real cameras — otherwise the file plays as fast as the disk allows and the
        # dashboard feed looks like a fast-forward. Live sources self-pace.
        self.frame_interval = 0.0
        if is_video:
            fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
            self.frame_interval = 1.0 / fps

        self.ret, self.frame, self.running = False, None, True
        self.frame_seq = 0   # monotonic counter so readers can de-dupe identical frames
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self) -> None:
        import cv2
        while self.running:
            # Pause support: block here while the pipeline is paused so video
            # doesn't advance (and the YOLO loop sees stale frames on resume).
            if self._pause_event is not None and not self._pause_event.is_set():
                time.sleep(0.05)
                continue
            t_start = time.time()
            ret, frame = self.cap.read()
            if ret:
                if self.resize_width and frame is not None:
                    h, w = frame.shape[:2]
                    if w > self.resize_width:
                        frame = cv2.resize(frame, (self.resize_width, int(self.resize_width * (h / w))), interpolation=cv2.INTER_LINEAR)
                with self.lock:
                    self.ret = True
                    self.frame = frame.copy() if frame is not None else None
                    self.frame_seq += 1
            elif self.is_video:
                # End of file → seek back to the original start_frame so the
                # video offset is preserved on every loop, not just the first play.
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, self._start_frame)
                continue
            else:
                # Live stream dropped (phone disconnected): release and retry in 2s.
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
                continue

            # Honor the per-source frame interval (video only).
            if self.frame_interval > 0:
                sleep = self.frame_interval - (time.time() - t_start)
                if sleep > 0:
                    time.sleep(sleep)

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        with self.lock:
            return self.ret, self.frame

    def read_with_seq(self) -> Tuple[bool, Optional[np.ndarray], int]:
        """Same as read() but also returns the monotonic frame counter, so a display
        loop can avoid re-encoding the same frame twice."""
        with self.lock:
            return self.ret, self.frame, self.frame_seq

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


_SENSOR_FIELDS = ("temperature", "vibration", "noise", "gas_h2s", "pressure")

def _merge_zone_states(redis_client: redis.Redis, cv_states: dict) -> None:
    """Merge CV pipeline output into rigvision:zones without touching SCADA sensor values.

    The pipeline owns: status, warning_reason, person_count, ppe_violations,
                       sensor_meta, label, floor, sensor_types, updated_at.
    SCADA publisher owns: temperature, vibration, noise, gas_h2s, pressure,
                          sensor_sources.
    On first write (zone not yet in Redis) the full cv_state is written so the
    key always exists for the frontend.
    """
    try:
        for zid, cv in cv_states.items():
            raw = redis_client.hget("rigvision:zones", zid)
            if not raw:
                # zone not yet in Redis — write full state
                redis_client.hset("rigvision:zones", zid, json.dumps(cv))
            else:
                z = json.loads(raw)
                # CV-owned fields
                z["status"]         = cv["status"]
                z["warning_reason"] = cv.get("warning_reason")
                z["person_count"]   = cv["person_count"]
                z["ppe_violations"] = cv["ppe_violations"]
                z["sensor_meta"]    = cv.get("sensor_meta", z.get("sensor_meta", {}))
                z["label"]          = cv.get("label", z.get("label", zid))
                z["floor"]          = cv.get("floor", z.get("floor", 0))
                z["sensor_types"]   = cv.get("sensor_types", z.get("sensor_types", []))
                z["updated_at"]     = cv["updated_at"]
                # SCADA-owned sensor fields: only write if SCADA hasn't set them yet
                for f in _SENSOR_FIELDS:
                    if f not in z or z[f] is None:
                        z[f] = cv.get(f)
                redis_client.hset("rigvision:zones", zid, json.dumps(z))
    except Exception as e:
        print(f"[redis] zone merge error: {e}")


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
        _merge_zone_states(redis_client, zone_states)
        frame_count += 1
        if frame_count % 50 == 0:
            print(f"  [demo] frame={frame_count} persons={len(persons)}")
        time.sleep(max(0, 0.1 - (time.time() - t_start)))  # ~10 Hz


# ── LIVE / VIDEO MODE (per-zone-group, in-process, direct-to-Redis) ─────────────
def _grab_frame(cap: ThreadedCamera, resize_width: Optional[int]):
    """Read the latest frame from a ThreadedCamera, optionally downscaled. Video EOF
    handling and native-FPS pacing both live inside ThreadedCamera now, so this helper
    is the same for live and video sources."""
    import cv2
    ret, frame = cap.read()
    if not ret or frame is None:
        return None
    if resize_width:
        h, w = frame.shape[:2]
        frame = cv2.resize(frame, (resize_width, int(resize_width * (h / w))), interpolation=cv2.INTER_LINEAR)
    return frame


class VideoFramePublisher:
    """Background thread that JPEG-encodes and publishes annotated video frames to
    Redis without blocking the YOLO loop."""

    def __init__(self, redis_client: redis.Redis, jpeg_quality: int = 70) -> None:
        import queue
        self.redis = redis_client
        self.jpeg_quality = jpeg_quality
        self._q: queue.Queue = queue.Queue(maxsize=8)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def publish(self, cam_id: int, frame: np.ndarray, tracks: list) -> None:
        try:
            self._q.put_nowait((cam_id, frame, tracks))
        except Exception:
            pass

    def _run(self) -> None:
        import cv2
        while True:
            cam_id, frame, tracks = self._q.get()
            try:
                annotated = frame.copy()
                for t in tracks:
                    x1, y1, x2, y2 = map(int, t.bbox)
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 200, 255), 2)
                    cv2.putText(annotated, f"#{t.track_id}", (x1, max(0, y1 - 8)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)
                ok, jpeg = cv2.imencode('.jpg', annotated,
                                        [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
                if ok:
                    self.redis.set(f"rigvision:camera:frame:{cam_id}",
                                   base64.b64encode(jpeg.tobytes()).decode('utf-8'), ex=2)
            except Exception as e:
                print(f"[video-pub] cam{cam_id} error: {e}")


class SyncedVideoReader:
    """Reads multiple video files in lockstep in a background thread — frame N from
    every file is consumed together so stereo pairs stay aligned. The main loop calls
    read() to get the latest ready pair without blocking on disk I/O."""

    def __init__(self, sources: Dict[int, str], offsets: Dict[int, int],
                 resize_width: Optional[int] = None,
                 pause_event: Optional[threading.Event] = None) -> None:
        import cv2
        self.caps: Dict[int, cv2.VideoCapture] = {}
        self.resize_width = resize_width
        self._pause_event = pause_event
        # Remember the per-camera start frame so every loop restarts at the
        # correct offset position, not at frame 0.
        self._start_frames: Dict[int, int] = {}
        for cam_id, path in sources.items():
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                raise RuntimeError(f"Cannot open video: {path}")
            skip = offsets.get(cam_id, 0)
            if skip > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, skip)
                print(f"[sync] cam{cam_id}: skipping {skip} frames to align")
            self._start_frames[cam_id] = skip
            self.caps[cam_id] = cap
        fps_vals = [c.get(cv2.CAP_PROP_FPS) or 30.0 for c in self.caps.values()]
        self._interval = 1.0 / (sum(fps_vals) / len(fps_vals))
        self._latest: Dict[int, Optional[np.ndarray]] = {}
        self._lock = threading.Lock()
        self._running = True
        # Incremented (under _lock) every time any camera hits EOF and loops.
        # The main loop watches this to know when to reset tracker state.
        self.loop_count = 0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        import cv2
        # The anchor camera has the smallest start offset. Its EOF marks the
        # end of one complete cycle. When it loops, ALL cameras are reset to
        # their respective start offsets so temporal alignment is restored.
        # Non-anchor cameras (with positive offsets) loop independently
        # mid-cycle — we just seek them back without signalling a full loop.
        anchor_cam = min(self._start_frames, key=lambda k: self._start_frames[k])
        while self._running:
            # Pause support: stop advancing video frames while paused so the
            # main loop sees stale frames (not new ones) on every paused tick.
            if self._pause_event is not None and not self._pause_event.is_set():
                time.sleep(0.05)
                continue
            t = time.time()
            frames: Dict[int, Optional[np.ndarray]] = {}

            # Read one frame from every camera.
            looped_this_batch = False
            for cam_id, cap in self.caps.items():
                ret, frame = cap.read()
                if not ret:
                    if cam_id == anchor_cam:
                        # Full cycle complete. Seek ALL cameras back to their
                        # individual start offsets so the inter-camera temporal
                        # gap stays exactly as configured on every loop. If only
                        # this camera were seeked, the other cameras would drift
                        # further ahead each cycle (22 frames → 44 → 66 → ...).
                        for cid, c in self.caps.items():
                            c.set(cv2.CAP_PROP_POS_FRAMES, self._start_frames.get(cid, 0))
                        looped_this_batch = True
                    else:
                        # Non-anchor hit its end mid-cycle (expected for cameras
                        # with a positive offset). Seek only this camera back.
                        cap.set(cv2.CAP_PROP_POS_FRAMES, self._start_frames.get(cam_id, 0))
                    ret, frame = cap.read()
                if ret and frame is not None and self.resize_width:
                    h, w = frame.shape[:2]
                    frame = cv2.resize(frame, (self.resize_width, int(self.resize_width * (h / w))),
                                       interpolation=cv2.INTER_LINEAR)
                frames[cam_id] = frame if ret else None

            with self._lock:
                self._latest = frames
                if looped_this_batch:
                    self.loop_count += 1
            sleep = self._interval - (time.time() - t)
            if sleep > 0:
                time.sleep(sleep)

    def read(self) -> Dict[int, Optional[np.ndarray]]:
        with self._lock:
            return dict(self._latest)

    def release(self) -> None:
        self._running = False
        self._thread.join(timeout=1.0)
        for cap in self.caps.values():
            cap.release()


def run_producer_mode(
    redis_client: redis.Redis,
    zone_defs: dict,
    sources: Dict[int, str],
    confidence: float = 0.5,
    model_path: str = "yolov8l.pt",
    device: Optional[str] = None,
    resize_width: Optional[int] = None,
    triag_width: Optional[int] = None,
    max_fps: Optional[float] = None,
    is_video: bool = False,
    video_offsets: Optional[Dict[int, int]] = None,
) -> None:
    # Load ArUco-ID → personnel name mapping from configs/personnel.json.
    # Keys are ArUco marker IDs (ints); values are display names.
    # Edit that file to add/remove mappings without touching this code.
    _personnel_names: Dict[int, str] = {}
    _personnel_path = Path(__file__).resolve().parent.parent / "configs" / "personnel.json"
    if _personnel_path.exists():
        try:
            with open(_personnel_path) as _f:
                _personnel_names = {int(k): v for k, v in json.load(_f).items()}
            print(f"[*] Personnel names loaded: {_personnel_names}")
        except Exception as _e:
            print(f"[warn] Could not load personnel names: {_e}")

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
    # Triangulation width is independent of YOLO resize width. Foot-points from YOLO
    # (in resize_width pixel space) are scaled up to triag_width before DLT, so the
    # effective focal length doubles and depth uncertainty halves — with zero extra cost
    # to YOLO inference. Calibration K/F are also loaded at triag_width.
    _triag_width = triag_width or (resize_width or 960)
    _foot_scale = _triag_width / (resize_width or _triag_width)
    zone_calibs = load_zone_calibrations(zone_groups, configs_dir, _triag_width)
    reproj_threshold = float(os.getenv("REPROJ_THRESHOLD", "80.0"))

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

    # Pause/Resume: a threading.Event controlled by a Redis key.
    # set   = pipeline running (normal)
    # clear = pipeline paused (YOLO loop + video readers all block)
    _pipeline_running = threading.Event()
    _pipeline_running.set()

    def _command_watcher() -> None:
        while not shutdown_event.is_set():
            try:
                paused = redis_client.get("rigvision:pipeline:paused") == "1"
                if paused and _pipeline_running.is_set():
                    _pipeline_running.clear()
                    print("[pipeline] PAUSED")
                elif not paused and not _pipeline_running.is_set():
                    _pipeline_running.set()
                    print("[pipeline] RESUMED")
            except Exception:
                pass
            time.sleep(0.2)

    threading.Thread(target=_command_watcher, daemon=True, name="cmd-watcher").start()

    # Video mode: SyncedVideoReader (background thread, lockstep) for YOLO,
    # plus ThreadedCamera per camera for the DisplayLoop feed.
    # Live mode: ThreadedCamera only (always-latest-frame, auto-reconnect).
    synced_reader: Optional[SyncedVideoReader] = None
    caps: Dict[int, ThreadedCamera] = {}
    if is_video:
        for src in sources.values():
            if not os.path.exists(src):
                print(f"Video not found: {src}")
                sys.exit(1)
        synced_reader = SyncedVideoReader(sources, video_offsets or {}, resize_width,
                                          pause_event=_pipeline_running)
    # In live-camera mode, ThreadedCamera grabs frames independently so DisplayLoop
    # can publish the MJPEG feed at the camera's native FPS without being gated on
    # YOLO speed.  In video mode we skip this: SyncedVideoReader is the only reader
    # of each file, so the YOLO loop annotates and publishes frames directly.
    # Having two independent cv2.VideoCapture objects on the same file causes them
    # to drift apart across loops, making bboxes appear ahead of or behind the person.
    if not is_video:
        for cam_id, src in sources.items():
            caps[cam_id] = ThreadedCamera(src, is_video=False, resize_width=resize_width,
                                          pause_event=_pipeline_running)

    latest_tracks = LatestTracks()
    display_fps = float(os.getenv("DISPLAY_FPS", "25"))
    display_loops = [
        DisplayLoop(redis_client, cid, cap, latest_tracks, target_fps=display_fps).start()
        for cid, cap in caps.items()
    ]

    # ── Optional: PPE compliance monitor (shares this pipeline's cameras) ────────
    # A second OIV7 model judges eye/head protection per person across one or more feeds.
    # A person's item shows DETECTED if ANY feed sees it (OR-merge in process_multi).
    # Throttled to every Nth tick (the debounce uses wall-clock time, so a slower sample
    # rate doesn't change the 3s windows).
    ppe_monitor = None
    # PPE_CAMERA_IDS is a comma list (e.g. "0,1"); PPE_CAMERA_ID kept as a fallback alias.
    _ppe_ids_env = os.getenv("PPE_CAMERA_IDS", os.getenv("PPE_CAMERA_ID", "0"))
    ppe_cam_ids = {int(x) for x in _ppe_ids_env.split(",") if x.strip() != ""}
    ppe_every_n = max(1, int(os.getenv("PPE_EVERY_N_FRAMES", "1")))
    if os.getenv("PPE_ENABLED", "1") not in ("0", "false", "False"):
        try:
            from PPE.ppe_monitor import PPEMonitor
            ppe_monitor = PPEMonitor(device=device)
            print(f"[*] PPE monitor enabled on cams {sorted(ppe_cam_ids)} (every {ppe_every_n} frames)")
        except Exception as e:
            print(f"[warn] PPE monitor disabled: {e}")

    _DEBUG_TRIAG = os.getenv("DEBUG_TRIANGULATION", "0") not in ("0", "false", "False")

    # ── PPE background thread ─────────────────────────────────────────────────
    # process_multi() runs face-YOLO + 2× EfficientNet on GPU — ~50-100ms per
    # call. Running it in a daemon thread lets the main loop keep producing
    # person positions without stalling on PPE inference.
    import queue as _queue
    _ppe_queue: "_queue.Queue" = _queue.Queue(maxsize=1)

    def _ppe_worker() -> None:
        while True:
            item = _ppe_queue.get()
            if item is None:
                break
            frames_snap, boxes_snap = item
            try:
                ppe_monitor.process_multi(frames_snap, boxes_snap, redis_client)
            except Exception as e:
                print(f"[ppe] process error: {e}")

    if ppe_monitor is not None:
        _ppe_thread = threading.Thread(target=_ppe_worker, daemon=True, name="ppe-worker")
        _ppe_thread.start()

    # Grace-period cache: a single bad triangulation tick (occlusion, transient
    # reprojection-error spike, momentary CCM mismatch) used to drop the person
    # entirely from persons_all for that tick, causing the frontend avatar +
    # sidebar to flicker to "lost" even though they're still visible in the raw
    # 2D feed. Hold the last good position for a short window instead.
    _TRIAG_GRACE_SECONDS = float(os.getenv("TRIAG_GRACE_SECONDS", "0.5"))
    _last_known_pos: Dict[int, Tuple[Tuple[float, float, float], float]] = {}

    # EMA smoothing on the triangulated 3D position.
    # A tight YOLO bbox or Kalman lag produces a wrong foot_point → wrong pos_world
    # for that tick. Blending with the recent EMA absorbs single-frame spikes while
    # still tracking genuine movement: at alpha=0.4, one bad frame contributes
    # only 40% of the output and real motion converges within 3-4 frames.
    _POS_EMA_ALPHA = float(os.getenv("POS_EMA_ALPHA", "0.4"))
    _pos_ema: Dict[int, Tuple[float, float, float]] = {}
    # Tracks which global_ids are currently being served from the grace-period
    # cache (i.e. triangulation failed last tick). When a gid transitions from
    # grace → fresh triangulation we bypass the EMA for that one frame so the
    # stale history from the occlusion doesn't drag the position sideways.
    _in_grace: set = set()
    # Consecutive-frame counter for each gid's valid triangulation.
    # We only write to _last_known_pos (the grace-period cache) once a person
    # has been cleanly triangulated for this many frames in a row. This prevents
    # a bad partial-bbox position from the first 1-2 frames of entry (when the
    # person is already partially behind someone) from poisoning the grace cache
    # and causing the avatar to lerp from a wrong location on re-emergence.
    _TRIAG_MIN_CONFIRMED = int(os.getenv("TRIAG_MIN_CONFIRMED", "3"))
    _triag_confirmed: Dict[int, int] = {}

    frame_count = 0
    _last_loop_count = 0  # tracks SyncedVideoReader.loop_count across ticks
    while not shutdown_event.is_set():
        # Block here while paused; the command-watcher thread sets/clears the event.
        _pipeline_running.wait()
        if shutdown_event.is_set():
            break

        # Detect video loop: when the reader wraps around, tracker IDs and
        # Kalman velocities from the previous pass are stale — the same people
        # reappear at the same positions but BoT-SORT thinks they jumped
        # discontinuously, which causes escalating reprojection errors.
        # Fresh tracker + matching state every loop keeps quality consistent.
        if synced_reader is not None and synced_reader.loop_count != _last_loop_count:
            _last_loop_count = synced_reader.loop_count
            print(f"[pipeline] Video loop #{_last_loop_count} — resetting tracker + matching state")
            for cam_id in list(trackers.keys()):
                trackers[cam_id] = BoTSORT(default_botsort_args(), frame_rate=30)
            matching_state.clear()
            matching_state.update({"previous_matches": {}, "aruco_matches": {}, "next_global_id": 100000})
            _last_known_pos.clear()
            _pos_ema.clear()
            _in_grace.clear()
            _triag_confirmed.clear()

        t_start = time.time()
        persons_all: List[dict] = []
        ppe_frames: Dict[int, np.ndarray] = {}
        ppe_person_cam_boxes: Dict[int, Dict[int, Tuple[float, float, float, float]]] = {}

        # In video mode, read all cameras in lockstep once per tick.
        synced_frames: Dict[int, Optional[np.ndarray]] = {}
        if synced_reader is not None:
            synced_frames = synced_reader.read()

        # ── Process each zone's camera pair INDEPENDENTLY ───────────────────────
        for zone_id, cam_ids in zone_groups.items():
            zdef = zone_defs["zones"][zone_id]
            zone_floor = zdef.get("floor", 0)

            frames: Dict[int, np.ndarray] = {}
            for cam_id in cam_ids:
                if synced_reader is not None:
                    f = synced_frames.get(cam_id)
                else:
                    cap = caps.get(cam_id)
                    f = _grab_frame(cap, resize_width) if cap else None
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

            # 4b. Per-person PPE: stash this zone's PPE-camera frames + each person's box
            #     on those cameras. The OR-merge across feeds happens after the zone loop.
            if ppe_monitor is not None and frame_count % ppe_every_n == 0:
                for cam_id in cam_ids:
                    if cam_id in ppe_cam_ids and cam_id in frames:
                        ppe_frames[cam_id] = frames[cam_id]
                for mp in matched:
                    for cam_id in ppe_cam_ids:
                        tp = mp.per_camera.get(cam_id)
                        if tp is not None:
                            ppe_person_cam_boxes.setdefault(int(mp.global_id), {})[cam_id] = tp.bbox

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
                            # Scale foot-points from YOLO's resize_width space to
                            # triag_width space. Same ray, larger f → halved depth error.
                            pt_a = (seen[a].foot_point[0] * _foot_scale,
                                    seen[a].foot_point[1] * _foot_scale)
                            pt_b = (seen[b].foot_point[0] * _foot_scale,
                                    seen[b].foot_point[1] * _foot_scale)
                            # Undistort before DLT: corrects k2≈-0.9 barrel/pincushion
                            # and the anamorphic fx/fy warp on cams calibrated via DroidCam.
                            pt_a = undistort_point(pt_a, cal_a.K, cal_a.dist_coeffs)
                            pt_b = undistort_point(pt_b, cal_b.K, cal_b.dist_coeffs)
                            pos_local = triangulate_dlt(pt_a, pt_b, cal_a.P, cal_b.P)
                            # Reprojection gate: if the two cameras were matched to
                            # different people, the 3D point won't reproject cleanly.
                            err = compute_reprojection_avg(pos_local, cal_a, cal_b, pt_a, pt_b)
                            if err < reproj_threshold:
                                pos_world = place_in_zone(pos_local, zdef)
                                if _DEBUG_TRIAG:
                                    print(f"[triangulation] Person {mp.global_id} OK: err={err:.2f}px pos={pos_world}")
                            else:
                                if _DEBUG_TRIAG:
                                    print(f"[triangulation] Person {mp.global_id} REJECTED: err={err:.2f}px >= thresh={reproj_threshold}")
                        except Exception as e:
                            print(f"[triangulation] ERROR Person {mp.global_id}: {e}")
                            pos_world = None

                gid = int(mp.global_id)
                now_t = time.time()
                if pos_world is None:
                    cached = _last_known_pos.get(gid)
                    if cached is not None and (now_t - cached[1]) < _TRIAG_GRACE_SECONDS:
                        pos_world = cached[0]
                        _in_grace.add(gid)
                        # Don't reset _triag_confirmed here — an established track
                        # (e.g. Vatsal) would lose its status on any single bad frame,
                        # causing the cache to go stale for 3+ frames and producing
                        # the same straight-line lerp artifact we're trying to fix.
                    else:
                        # Grace fully expired: person truly gone.  Reset so the next
                        # appearance must earn MIN_CONFIRMED fresh frames before the
                        # cache is written — prevents a reappearing person's first
                        # partial-bbox frames from poisoning the grace cache.
                        _in_grace.discard(gid)
                        _triag_confirmed.pop(gid, None)
                        continue
                else:
                    # On re-emergence from occlusion, bypass the EMA for this one
                    # frame so stale history from the occlusion doesn't drag the
                    # avatar sideways. The Kalman velocity was wrong during the
                    # occluded period; jumping straight to the new raw position
                    # (alpha=1.0) lets the EMA start fresh from a clean baseline.
                    just_emerged = gid in _in_grace
                    _in_grace.discard(gid)
                    prev = _pos_ema.get(gid)
                    if prev is not None and not just_emerged:
                        a = _POS_EMA_ALPHA
                        pos_world = (
                            round(a * pos_world[0] + (1 - a) * prev[0], 2),
                            round(a * pos_world[1] + (1 - a) * prev[1], 2),
                            round(a * pos_world[2] + (1 - a) * prev[2], 2),
                        )
                    _pos_ema[gid] = pos_world
                    # Only cache this position for the grace period once we've
                    # seen clean triangulation for MIN_CONFIRMED consecutive frames.
                    # A person entering the frame while already partially behind
                    # someone else typically has a bad foot_point for the first
                    # 1-2 frames — if we cached that and they immediately go fully
                    # occluded, the grace period would serve the wrong position and
                    # the THREE.js lerp would drift the avatar sideways for seconds.
                    _triag_confirmed[gid] = _triag_confirmed.get(gid, 0) + 1
                    if _triag_confirmed[gid] >= _TRIAG_MIN_CONFIRMED:
                        _last_known_pos[gid] = (pos_world, now_t)

                best = max(seen.values(), key=lambda tr: tr.confidence)
                # Per-person PPE (glasses/hat) from the monitor's latest debounced status,
                # keyed by this person's global id. Unknown until they're seen on the PPE
                # camera for the debounce window.
                if ppe_monitor is not None:
                    person_ppe = ppe_monitor.last_person_status.get(
                        int(mp.global_id), dict(DEFAULT_PPE))
                else:
                    person_ppe = dict(DEFAULT_PPE)
                persons_all.append({
                    "id": int(mp.global_id),
                    "name": _personnel_names.get(int(mp.global_id)),  # None if not in mapping
                    "x": pos_world[0], "y": pos_world[1], "z": pos_world[2],
                    "zone": zone_id,                       # exact: group-derived, not guessed
                    "floor": zone_floor,
                    "posture": getattr(best, "posture", "standing"),
                    "ppe": person_ppe,                     # {"glasses": ..., "hat": ...}
                    "confidence": round(float(best.confidence), 2),
                    "cameras_visible": len(seen),
                    "camera_ids": cams_in_view,
                })

            for cam_id in frames.keys():
                latest_tracks.set(cam_id, per_camera_tracks.get(cam_id, []))

            # In video mode there is no DisplayLoop — publish annotated frames
            # directly from the frames YOLO just processed so bboxes are always
            # drawn on exactly the right frame (no independent reader drift).
            if synced_reader is not None:
                import cv2 as _cv2
                for cam_id, frame in frames.items():
                    if frame is None:
                        continue
                    annotated = frame.copy()
                    fh, fw = annotated.shape[:2]
                    for t in per_camera_tracks.get(cam_id, []):
                        bx1, by1, bx2, by2 = t.bbox
                        bw, bh = bx2 - bx1, by2 - by1
                        x1 = max(0,  int(bx1 - 0.12 * bw))
                        y1 = max(0,  int(by1 - 0.05 * bh))
                        x2 = min(fw, int(bx2 + 0.12 * bw))
                        y2 = min(fh, int(by2 + 0.05 * bh))
                        _cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 200, 255), 2)
                        label = f"#{t.track_id}"
                        if getattr(t, "aruco_id", None) is not None:
                            label += f" (ARUCO {t.aruco_id})"
                        _cv2.putText(annotated, label, (x1, max(0, y1 - 8)),
                                     _cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)
                    ok, jpeg = _cv2.imencode('.jpg', annotated,
                                            [int(_cv2.IMWRITE_JPEG_QUALITY), 75])
                    if ok:
                        try:
                            redis_client.set(
                                f"rigvision:camera:frame:{cam_id}",
                                base64.b64encode(jpeg.tobytes()).decode('utf-8'),
                                ex=3,
                            )
                        except Exception:
                            pass

        # Prune grace-period cache entries that haven't refreshed in a while —
        # the person has genuinely left, not just hit a transient triangulation miss.
        _prune_before = time.time() - (_TRIAG_GRACE_SECONDS * 4)
        for gid in [g for g, (_, ts) in _last_known_pos.items() if ts < _prune_before]:
            _last_known_pos.pop(gid, None)

        # ── PPE: hand off to background thread (non-blocking) ────────────────
        if ppe_monitor is not None and ppe_frames and frame_count % ppe_every_n == 0:
            try:
                _ppe_queue.put_nowait((dict(ppe_frames), dict(ppe_person_cam_boxes)))
            except _queue.Full:
                pass  # PPE thread still busy with previous frame — skip this tick

        # ── Fuse sensors + occupancy into zone state and publish to Redis ───────
        sensor_readings = read_sensor_readings(redis_client)
        resolved_thresholds = read_resolved_thresholds(redis_client)
        zone_states = build_zone_states(persons_all, sensor_readings, zone_defs, resolved_thresholds)
        try:
            redis_client.set("rigvision:persons", json.dumps(persons_all))
            _merge_zone_states(redis_client, zone_states)
        except Exception as e:
            print(f"[redis] write error: {e}")

        frame_count += 1
        elapsed = time.time() - t_start
        if frame_count % 30 == 0:
            print(f"  [producer] frame={frame_count} persons={len(persons_all)} fps={1.0/max(elapsed,1e-3):.1f}")
        if max_fps:
            time.sleep(max(0, (1.0 / max_fps) - elapsed))

    for dl in display_loops:
        dl.stop()
    if synced_reader is not None:
        synced_reader.release()
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
    parser.add_argument("--resize-width", type=int, default=960)
    parser.add_argument("--triag-width", type=int, default=1920,
                        help="Pixel width used for triangulation math only (not YOLO). "
                             "Foot-points are scaled from resize-width to this before DLT. "
                             "Higher = better depth precision, no YOLO speed cost.")
    parser.add_argument("--max-fps", type=float, default=None)
    parser.add_argument("--video-offsets", nargs="+", default=None,
                        help="Per-camera start-frame offsets: cam_id=frames e.g. --video-offsets 1=45")
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

    video_offsets: Dict[int, int] = {}
    if args.video_offsets:
        for entry in args.video_offsets:
            cam_id_str, frames_str = entry.split("=")
            video_offsets[int(cam_id_str)] = int(frames_str)

    run_producer_mode(
        redis_client=redis_client, zone_defs=zone_defs, sources=sources,
        confidence=args.confidence, model_path=args.model, device=args.device,
        resize_width=args.resize_width, triag_width=args.triag_width, max_fps=args.max_fps,
        is_video=(args.mode == "video"), video_offsets=video_offsets,
    )


if __name__ == "__main__":
    main()
