"""RigVision-3D — Main CV Pipeline"""
from __future__ import annotations
import argparse, base64, json, math, os, queue, signal, sys, threading, time
from typing import List, Optional, Tuple
import numpy as np
import redis

os.environ["OPENCV_LOG_LEVEL"] = "OFF"
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tracking.triangulation import load_zones, assign_zone

shutdown_event = threading.Event()
clear_tracking_cache_event = threading.Event()
DEFAULT_PPE = {"hardhat": None, "vest": None, "goggles": None}
PERSON_UPDATE_FIELDS = ("x", "y", "z", "zone", "floor", "posture", "ppe", "confidence")

# Sensor fusion: canonical types surfaced in zone state, and how long a reading
# stays valid before it's treated as "unknown" (sensor offline / disconnected).
CANONICAL_SENSOR_TYPES = ("temperature", "vibration", "noise", "gas_h2s", "pressure")
SENSOR_STALE_SECONDS = float(os.getenv("SENSOR_STALE_SECONDS", "10"))
SENSORS_KEY = "rigvision:sensors:latest"
_SEVERITY = {"normal": 0, "warning": 1, "critical": 2}

def signal_handler(sig: int, frame: object) -> None:
    shutdown_event.set()

signal.signal(signal.SIGINT, signal_handler)

def redis_command_listener(redis_client: redis.Redis) -> None:
    pubsub = redis_client.pubsub()
    try:
        pubsub.subscribe("rigvision:commands")
        while not shutdown_event.is_set():
            msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if msg and msg.get("data") == "clear_cache":
                clear_tracking_cache_event.set()
            time.sleep(0.1)
    except Exception as e:
        print(f"[commands] Error: {e}")

def load_zone_definitions(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)

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
                if not ok:
                    continue
                redis_client.set(f"rigvision:camera:frame:{cam_id}", base64.b64encode(jpeg.tobytes()).decode('utf-8'), ex=2)
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

def annotate_and_enqueue(
    frame: np.ndarray,
    cam_id: int,
    tracks: list,
    local_to_personnel_map: dict,
    local_to_recognition_method: dict,
    global_id_offset: Optional[int],
    global_to_personnel_map: dict,
    global_to_recognition_method: dict,
    upload_queue: queue.Queue,
    show_preview: bool,
    label_cache: Optional[dict] = None,
) -> None:
    import cv2
    annotated = frame.copy()
    for t in tracks:
        x1, y1, x2, y2 = map(int, t.bbox)
        color = (0, 255, 0) if (t.ppe and t.ppe.get("hardhat") is True) else (0, 0, 255)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        if label_cache and (cam_id, t.track_id) in label_cache:
            lbl = label_cache[(cam_id, t.track_id)]
        elif (cam_id, t.track_id) in local_to_personnel_map:
            lbl = f"#{local_to_personnel_map[(cam_id, t.track_id)]} ({local_to_recognition_method.get((cam_id, t.track_id), 'face').upper()})"
        else:
            lbl = f"#{t.track_id + (global_id_offset or 0)}"
        cv2.putText(annotated, lbl, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        _draw_skeleton(annotated, getattr(t, 'keypoints', None))
    _queue_latest_frame(upload_queue, cam_id, annotated)
    if show_preview:
        cv2.imshow(f"Camera {cam_id}", annotated)

def _ppe_or_unknown(ppe: Optional[dict]) -> dict:
    return dict(ppe) if ppe else dict(DEFAULT_PPE)

def _merge_person_observation(existing: dict, candidate: dict) -> None:
    previous_visible = existing.get("cameras_visible", len(existing.get("camera_ids", [])))
    candidate_visible = candidate.get("cameras_visible", len(candidate.get("camera_ids", [])))
    previous_confidence = existing.get("confidence", 0.0)
    candidate_confidence = candidate.get("confidence", 0.0)

    candidate_is_better = (
        candidate_visible > previous_visible
        or (candidate_visible == previous_visible and candidate_confidence > previous_confidence)
    )

    if candidate_is_better:
        for key in PERSON_UPDATE_FIELDS:
            if key in candidate:
                existing[key] = candidate[key]

    if candidate.get("recognition_method") and not existing.get("recognition_method"):
        existing["recognition_method"] = candidate["recognition_method"]

    camera_ids = set(existing.get("camera_ids", []))
    camera_ids.update(candidate.get("camera_ids", []))
    existing["camera_ids"] = sorted(camera_ids)
    existing["cameras_visible"] = len(existing["camera_ids"])

def propagate_recognition(
    matched_persons: list,
    global_to_personnel_map: dict[int, int],
    global_to_recognition_method: dict[int, str],
    local_to_personnel_map: dict[tuple[int, int], int],
    local_to_recognition_method: dict[tuple[int, int], str],
) -> None:
    for mp in matched_persons:
        rec_id, rec_meth = None, None
        for cam_id, track in mp.per_camera.items():
            if getattr(track, "face_id", None) is not None:
                rec_id, rec_meth = track.face_id, track.recognition_method
                break
        if rec_id is not None:
            global_to_personnel_map[mp.global_id] = rec_id
            global_to_recognition_method[mp.global_id] = rec_meth
            for cid, track in mp.per_camera.items():
                local_to_personnel_map[(cid, track.track_id)] = rec_id
                local_to_recognition_method[(cid, track.track_id)] = rec_meth
        elif mp.global_id in global_to_personnel_map:
            pid = global_to_personnel_map[mp.global_id]
            meth = global_to_recognition_method[mp.global_id]
            for cid, track in mp.per_camera.items():
                local_to_personnel_map[(cid, track.track_id)] = pid
                local_to_recognition_method[(cid, track.track_id)] = meth
        else:
            for cid, track in mp.per_camera.items():
                if (cid, track.track_id) in local_to_personnel_map:
                    pid = local_to_personnel_map[(cid, track.track_id)]
                    meth = local_to_recognition_method[(cid, track.track_id)]
                    global_to_personnel_map[mp.global_id] = pid
                    global_to_recognition_method[mp.global_id] = meth
                    for cid2, track2 in mp.per_camera.items():
                        local_to_personnel_map[(cid2, track2.track_id)] = pid
                        local_to_recognition_method[(cid2, track2.track_id)] = meth
                    break

def build_fused_persons(
    matched_persons: list,
    global_to_personnel_map: dict[int, int],
    global_to_recognition_method: dict[int, str],
) -> list[dict]:
    fused: dict[int, dict] = {}
    for mp in matched_persons:
        if mp.position_3d is None:
            continue
        best = max(mp.per_camera.values(), key=lambda t: t.confidence)
        pid = global_to_personnel_map.get(mp.global_id, mp.global_id)
        posture = getattr(best, "posture", "standing")
        p_dict = {
            "id": pid,
            "x": round(mp.position_3d[0], 2),
            "y": round(mp.position_3d[1], 2),
            "z": round(mp.position_3d[2], 2),
            "zone": mp.zone or "unknown",
            "floor": 1 if (mp.zone and mp.zone.endswith("_f1")) else 0,
            "posture": posture,
            "ppe": _ppe_or_unknown(best.ppe),
            "confidence": round(best.confidence, 2),
            "cameras_visible": len(mp.per_camera),
            "camera_ids": sorted(int(cid) for cid in mp.per_camera.keys()),
            "recognition_method": global_to_recognition_method.get(mp.global_id) if mp.global_id in global_to_personnel_map else None,
        }
        if pid in fused:
            _merge_person_observation(fused[pid], p_dict)
        else:
            fused[pid] = p_dict
    return list(fused.values())

def _draw_skeleton(frame: np.ndarray, keypoints: Optional[np.ndarray]) -> None:
    import cv2
    if keypoints is None or len(keypoints) == 0: return
    for s, e in [(5, 6), (5, 11), (6, 12), (11, 12), (5, 7), (7, 9), (6, 8), (8, 10), (11, 13), (13, 15), (12, 14), (14, 16), (0, 1), (0, 2), (1, 3), (2, 4)]:
        if s < len(keypoints) and e < len(keypoints):
            p1, p2 = tuple(map(int, keypoints[s])), tuple(map(int, keypoints[e]))
            if p1 != (0, 0) and p2 != (0, 0): cv2.line(frame, p1, p2, (0, 255, 255), 2)
    for kp in keypoints:
        p = tuple(map(int, kp))
        if p != (0, 0): cv2.circle(frame, p, 4, (0, 0, 255), -1)

def _evict_stale_tracks(
    per_camera_tracks: dict[int, list],
    local_to_personnel_map: dict,
    local_to_recognition_method: dict,
    global_to_personnel_map: dict,
    global_to_recognition_method: dict,
    active_global_ids: set,
    mapper: Optional[object],
) -> None:
    active_local = {(cam_id, track.track_id) for cam_id, tracks in per_camera_tracks.items() for track in tracks}
    for k in list(local_to_personnel_map.keys()):
        if k not in active_local:
            local_to_personnel_map.pop(k, None)
            local_to_recognition_method.pop(k, None)
    for gid in list(global_to_personnel_map.keys()):
        if gid not in active_global_ids:
            global_to_personnel_map.pop(gid, None)
            global_to_recognition_method.pop(gid, None)
    if mapper is not None and hasattr(mapper, 'previous_matches'):
        for k in list(mapper.previous_matches.keys()):
            if k not in active_local:
                mapper.previous_matches.pop(k, None)

def _read_sensor_readings(redis_client: redis.Redis) -> dict:
    """Read the sensor seam (rigvision:sensors:latest). Source-agnostic: the
    manual dashboard writes it today, an MQTT bridge will write it tomorrow."""
    try:
        raw = redis_client.get(SENSORS_KEY)
        return json.loads(raw) if raw else {}
    except Exception as e:
        print(f"[sensors] read error: {e}")
        return {}

def build_zone_states(persons: list[dict], sensor_readings: dict, zone_defs: dict) -> dict:
    """Fuse live sensor readings + person occupancy/PPE into per-zone state.

    Sensor values come from `sensor_readings` (keyed by sensor_id). Each reading is
    validated for freshness (SENSOR_STALE_SECONDS); stale/missing → treated as unknown
    (None). Multiple sensors of the same type in a zone are aggregated worst-case (max).
    Zone status escalates from sensor thresholds, PPE violations, and occupancy.
    """
    now = time.time()
    states = {}
    for zid, zdef in zone_defs["zones"].items():
        z_pers = [p for p in persons if p["zone"] == zid]
        ppe_viol = []
        for p in z_pers:
            ppe = p.get("ppe", {})
            if ppe.get("hardhat") is False: ppe_viol.append(f"Person #{p['id']} missing hard hat")
            if ppe.get("vest") is False: ppe_viol.append(f"Person #{p['id']} missing vest")

        by_type: dict[str, list[float]] = {t: [] for t in CANONICAL_SENSOR_TYPES}
        status, reason = "normal", None

        for s in zdef.get("sensors", []):
            reading = sensor_readings.get(s["id"])
            value = None
            if reading is not None:
                v = reading.get("value")
                if v is not None:
                    # Manual set-points persist until changed; live sensors (mqtt/sim)
                    # expire after SENSOR_STALE_SECONDS so a disconnect shows as unknown.
                    is_manual = reading.get("source") == "manual"
                    fresh = is_manual or (now - reading.get("updated_at", 0)) <= SENSOR_STALE_SECONDS
                    if fresh:
                        value = float(v)
            if value is None:
                continue  # missing or stale → unknown, skip

            stype = s["type"]
            if stype in by_type:
                by_type[stype].append(value)

            crit, warn, unit = s.get("critical"), s.get("warning"), s.get("unit", "")
            if crit is not None and value >= crit and _SEVERITY["critical"] > _SEVERITY[status]:
                status, reason = "critical", f"{stype} {value:.1f}{unit} >= critical ({crit}) [{s['id']}]"
            elif warn is not None and value >= warn and _SEVERITY["warning"] > _SEVERITY[status]:
                status, reason = "warning", f"{stype} {value:.1f}{unit} >= warning ({warn}) [{s['id']}]"

        if ppe_viol and _SEVERITY["warning"] > _SEVERITY[status]:
            status, reason = "warning", f"{len(ppe_viol)} PPE violation(s)"
        max_occ = zdef.get("max_occupancy", 99)
        if len(z_pers) > max_occ and _SEVERITY["critical"] > _SEVERITY[status]:
            status, reason = "critical", f"Overcrowded: {len(z_pers)}/{max_occ} persons"

        agg = {t: (round(max(by_type[t]), 2) if by_type[t] else None) for t in CANONICAL_SENSOR_TYPES}
        present_types = sorted({s["type"] for s in zdef.get("sensors", [])})
        states[zid] = {
            "status": status, "warning_reason": reason,
            "label": zdef.get("name", zid),
            "floor": zdef.get("floor", 0),
            "sensor_types": present_types,
            "temperature": agg["temperature"], "vibration": agg["vibration"],
            "noise": agg["noise"], "gas_h2s": agg["gas_h2s"], "pressure": agg["pressure"],
            "person_count": len(z_pers), "ppe_violations": ppe_viol, "updated_at": int(time.time()),
        }
    return states

def _handle_cache_clear(g_map, g_meth, l_map, l_meth, trackers) -> None:
    if clear_tracking_cache_event.is_set():
        g_map.clear()
        g_meth.clear()
        l_map.clear()
        l_meth.clear()
        for t in trackers.values(): t.reset()
        clear_tracking_cache_event.clear()

def _publish_fps(redis_client: redis.Redis, fps: float) -> None:
    try:
        redis_client.set("rigvision:pipeline:fps", str(round(fps, 1)), ex=10)
    except Exception:
        pass

def _normalize_floor_map(floor_map: Optional[List[int]], source_count: int) -> List[int]:
    normalized = list(floor_map or [])[:source_count]
    normalized.extend([0] * (source_count - len(normalized)))
    return normalized

def _track_frames(frames: dict[int, np.ndarray], detector, trackers: dict[int, object]) -> dict[int, list]:
    source_ids = sorted(frames.keys())
    frame_list = [frames[source_id] for source_id in source_ids]
    batch_detections = detector.detect_batch(frame_list)
    return {
        source_id: trackers[source_id].update(frames[source_id], batch_detections[index])
        for index, source_id in enumerate(source_ids)
    }

def _write_realtime_state(redis_client: redis.Redis, persons: list[dict], zone_defs: dict) -> dict:
    sensor_readings = _read_sensor_readings(redis_client)
    zone_states = build_zone_states(persons, sensor_readings, zone_defs)
    try:
        redis_client.set("rigvision:persons", json.dumps(persons))
        redis_client.set("rigvision:zones", json.dumps(zone_states))
    except Exception as e:
        print(f"Redis write error: {e}")
    return zone_states

def _publish_annotated_frames(
    frames: dict[int, np.ndarray],
    tracks_by_source: dict[int, list],
    local_to_personnel_map: dict,
    local_to_recognition_method: dict,
    global_to_personnel_map: dict,
    global_to_recognition_method: dict,
    upload_queue: queue.Queue,
    show_preview: bool,
    global_id_offsets: Optional[dict[int, int]] = None,
    label_cache: Optional[dict] = None,
) -> None:
    for source_id, frame in frames.items():
        annotate_and_enqueue(
            frame,
            source_id,
            tracks_by_source.get(source_id, []),
            local_to_personnel_map,
            local_to_recognition_method,
            global_id_offsets.get(source_id) if global_id_offsets else None,
            global_to_personnel_map,
            global_to_recognition_method,
            upload_queue,
            show_preview,
            label_cache,
        )

def _finish_frame(
    redis_client: redis.Redis,
    mode_name: str,
    frame_count: int,
    frame_started_at: float,
    person_count: int,
    max_fps: Optional[float],
) -> int:
    frame_count += 1
    elapsed = time.time() - frame_started_at
    if frame_count % 30 == 0:
        fps_actual = 1.0 / max(elapsed, 0.001)
        print(f"  [{mode_name}] frame={frame_count} persons={person_count} fps={fps_actual:.1f}")
        _publish_fps(redis_client, fps_actual)
    if max_fps:
        time.sleep(max(0, (1.0 / max_fps) - elapsed))
    return frame_count

def _shutdown_uploader(upload_queue: queue.Queue, uploader_thread: threading.Thread) -> None:
    try:
        upload_queue.put(None, timeout=1.0)
    except queue.Full:
        pass
    uploader_thread.join(timeout=1.0)

class DemoDataGenerator:
    def __init__(self, zone_definitions_path: str, num_persons: int = 4) -> None:
        self.zone_defs = load_zone_definitions(zone_definitions_path)
        self.num_persons = num_persons
        self.start_time = time.time()
        self.zones = load_zones(zone_definitions_path)
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
            zone = assign_zone(self.zones, x, y, z)
            if np.random.random() < 0.002: p["has_hardhat"] = not p["has_hardhat"]
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
    print("[*] Starting DEMO mode (simulated people, real sensor feed)... Press Ctrl+C to stop")
    generator = DemoDataGenerator(zone_definitions_path, num_persons=4)
    zone_defs = load_zone_definitions(zone_definitions_path)
    frame_count = 0
    while not shutdown_event.is_set():
        t_start = time.time()
        persons = generator.generate_persons()
        sensor_readings = _read_sensor_readings(redis_client)
        zone_states = build_zone_states(persons, sensor_readings, zone_defs)
        redis_client.set("rigvision:persons", json.dumps(persons))
        redis_client.set("rigvision:zones", json.dumps(zone_states))
        frame_count += 1
        if frame_count % 50 == 0:
            print(f"  [demo] frame={frame_count} persons={len(persons)} zones={ {z: s['status'] for z, s in zone_states.items()} }")
        time.sleep(max(0, 0.1 - (time.time() - t_start)))

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
                with self.lock: self.ret = False
                self.cap.release()
                time.sleep(2.0)
                if not self.running: break
                try:
                    self.cap = cv2.VideoCapture(int(self.source) if self.is_usb else self.source)
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    if self.is_usb:
                        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                except Exception as e:
                    print(f"Reconnect error: {e}")
                time.sleep(1.0)

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        with self.lock: return self.ret, self.frame
    def get(self, propId: int) -> float: return self.cap.get(propId)
    def release(self) -> None:
        self.running = False
        self.thread.join(timeout=1.0)
        self.cap.release()

def run_live_mode(
    redis_client: redis.Redis,
    camera_sources: List[str],
    zone_definitions_path: str,
    calibration_dir: str,
    confidence: float = 0.5,
    model_path: str = "yolov8l.pt",
    show_preview: bool = False,
    device: Optional[str] = None,
    resize_width: Optional[int] = None,
    max_fps: Optional[float] = None,
    floor_map: Optional[List[int]] = None,
) -> None:
    floor_map = _normalize_floor_map(floor_map, len(camera_sources))
    import cv2
    from detection.detector import PersonDetector
    from tracking.tracker import PersonTracker
    from tracking.cross_camera import CrossCameraMapper
    from tracking.triangulation import CameraCalibration, load_calibrations, triangulate_all

    print(f"[*] Starting LIVE mode with {len(camera_sources)} camera(s)")
    detector = PersonDetector(model_path=model_path, confidence=confidence, device=device)
    cameras = {i: ThreadedCamera(src) for i, src in enumerate(camera_sources)}
    calibrations = load_calibrations(calibration_dir)
    for i in cameras:
        if i not in calibrations: calibrations[i] = CameraCalibration.create_default(i)
    trackers = {i: PersonTracker(camera_id=i) for i in cameras}
    mapper = CrossCameraMapper()
    tri_zones = load_zones(zone_definitions_path)
    zone_defs = load_zone_definitions(zone_definitions_path)
    upload_queue = queue.Queue(maxsize=30)
    uploader_thread = create_redis_uploader(redis_client, upload_queue)

    global_to_personnel_map, global_to_recognition_method = {}, {}
    local_to_personnel_map, local_to_recognition_method = {}, {}
    frame_count = 0

    while not shutdown_event.is_set():
        _handle_cache_clear(global_to_personnel_map, global_to_recognition_method, local_to_personnel_map, local_to_recognition_method, trackers)
        t_start = time.time()
        frames = {}
        for cam_id, cap in cameras.items():
            ret, frame = cap.read()
            if ret:
                if cam_id in calibrations:
                    frame = cv2.undistort(frame, calibrations[cam_id].K, calibrations[cam_id].dist_coeffs)
                if resize_width:
                    h, w = frame.shape[:2]
                    frame = cv2.resize(frame, (resize_width, int(resize_width * (h / w))), interpolation=cv2.INTER_LINEAR)
                frames[cam_id] = frame
        if not frames:
            time.sleep(0.02)
            continue

        per_camera_tracks = _track_frames(frames, detector, trackers)

        matched_persons = mapper.match(per_camera_tracks)
        matched_persons = triangulate_all(matched_persons, calibrations, tri_zones, floor_map)
        propagate_recognition(matched_persons, global_to_personnel_map, global_to_recognition_method, local_to_personnel_map, local_to_recognition_method)

        persons_json = build_fused_persons(
            matched_persons,
            global_to_personnel_map,
            global_to_recognition_method,
        )
        _write_realtime_state(redis_client, persons_json, zone_defs)

        _publish_annotated_frames(
            frames,
            per_camera_tracks,
            local_to_personnel_map,
            local_to_recognition_method,
            global_to_personnel_map,
            global_to_recognition_method,
            upload_queue,
            show_preview,
        )
        if show_preview and cv2.waitKey(1) & 0xFF == ord('q'): break

        _evict_stale_tracks(per_camera_tracks, local_to_personnel_map, local_to_recognition_method, global_to_personnel_map, global_to_recognition_method, {mp.global_id for mp in matched_persons}, mapper)
        frame_count = _finish_frame(redis_client, "live", frame_count, t_start, len(persons_json), max_fps)

    _shutdown_uploader(upload_queue, uploader_thread)
    for cap in cameras.values(): cap.release()
    if show_preview: cv2.destroyAllWindows()

def run_video_mode(
    redis_client: redis.Redis,
    video_paths: List[str],
    zone_definitions_path: str,
    confidence: float = 0.5,
    model_path: str = "yolov8l.pt",
    show_preview: bool = False,
    device: Optional[str] = None,
    resize_width: Optional[int] = None,
    max_fps: Optional[float] = None,
    floor_map: Optional[List[int]] = None,
) -> None:
    floor_map = _normalize_floor_map(floor_map, len(video_paths))
    resize_width = resize_width or 640
    import cv2
    from detection.detector import PersonDetector
    from tracking.tracker import PersonTracker

    print(f"[*] Starting VIDEO mode with {video_paths}")
    for vp in video_paths:
        if not os.path.exists(vp):
            print(f"Video not found: {vp}")
            sys.exit(1)

    zone_defs = load_zone_definitions(zone_definitions_path)
    zone_ids = list(zone_defs["zones"].keys())
    video_zone_map = {i: (zone_ids[min(i, len(zone_ids) - 1)] if len(video_paths) > 2 else "zone_a") for i in range(len(video_paths))}
    detector = PersonDetector(model_path=model_path, confidence=confidence, device=device)

    caps, trackers, frame_sizes = {}, {}, {}
    for i, vp in enumerate(video_paths):
        cap = cv2.VideoCapture(vp)
        if not cap.isOpened():
            print(f"Cannot open: {vp}")
            sys.exit(1)
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        caps[i] = cap
        trackers[i] = PersonTracker(camera_id=i)
        frame_sizes[i] = (resize_width, int(resize_width * (h / w)))

    zone_bounds = {zid: {"min_x": zdef["bounds"]["min"]["x"], "max_x": zdef["bounds"]["max"]["x"], "min_z": zdef["bounds"]["min"]["z"], "max_z": zdef["bounds"]["max"]["z"]} for zid, zdef in zone_defs["zones"].items()}
    upload_queue = queue.Queue(maxsize=30)
    uploader_thread = create_redis_uploader(redis_client, upload_queue)

    global_to_personnel_map, global_to_recognition_method = {}, {}
    local_to_personnel_map, local_to_recognition_method = {}, {}
    frame_count = 0
    global_id_offset = {i: i * 100 for i in range(len(video_paths))}

    def get_hist(frm, bbox):
        x1, y1, x2, y2 = map(int, bbox)
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(frm.shape[1], x2), min(frm.shape[0], y2)
        crop = frm[y1:y2, x1:x2]
        if crop.size == 0: return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [8, 8], [0, 180, 0, 256])
        return cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)

    while not shutdown_event.is_set():
        _handle_cache_clear(global_to_personnel_map, global_to_recognition_method, local_to_personnel_map, local_to_recognition_method, trackers)
        t_start = time.time()
        frames = {}
        for vid_id, cap in caps.items():
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()
                if not ret: continue
            h, w = frame.shape[:2]
            frames[vid_id] = cv2.resize(frame, (resize_width, int(resize_width * (h / w))), interpolation=cv2.INTER_LINEAR)
        if not frames: break

        per_video_tracks = _track_frames(frames, detector, trackers)

        fused_persons_dict, person_matched_info, anchor_hists, active_global_ids = {}, {}, {}, set()
        for vid_id in sorted(frames.keys()):
            tracked = per_video_tracks[vid_id]
            zone_id = f"{video_zone_map[vid_id]}_f1" if (floor_map[vid_id] == 1 and not video_zone_map[vid_id].endswith("_f1")) else video_zone_map[vid_id]
            zb = zone_bounds[zone_id]
            fw, fh = frame_sizes[vid_id]

            for p in tracked:
                if getattr(p, "face_id", None) is not None:
                    local_to_personnel_map[(vid_id, p.track_id)] = p.face_id
                    local_to_recognition_method[(vid_id, p.track_id)] = p.recognition_method
                elif (vid_id, p.track_id) in local_to_personnel_map:
                    p.face_id = local_to_personnel_map[(vid_id, p.track_id)]
                    p.recognition_method = local_to_recognition_method[(vid_id, p.track_id)]

            for p in tracked:
                fx, fy = p.foot_point
                room_x = zb["min_x"] + (fx / fw) * (zb["max_x"] - zb["min_x"])
                room_z = zb["max_z"] - (fy / fh) * (zb["max_z"] - zb["min_z"])
                room_y = floor_map[vid_id] * 3.0 + 0.05
                final_id = p.track_id + global_id_offset[vid_id]
                hist = get_hist(frames[vid_id], p.bbox)
                matched_with_anchor, matched_anchor_id, matched_dist = False, None, None

                if vid_id == 0:
                    if hist is not None: anchor_hists[final_id] = hist
                elif hist is not None:
                    best_match, best_dist = None, 0.55
                    for aid, ahist in anchor_hists.items():
                        dist = cv2.compareHist(hist, ahist, cv2.HISTCMP_BHATTACHARYYA)
                        if dist < best_dist: best_dist, best_match = dist, aid
                    if best_match is not None:
                        final_id = best_match
                        matched_with_anchor, matched_anchor_id, matched_dist = True, best_match, best_dist

                active_global_ids.add(final_id)
                person_matched_info[(vid_id, p.track_id)] = (matched_with_anchor, matched_anchor_id, matched_dist)
                if getattr(p, "face_id", None) is not None:
                    global_to_personnel_map[final_id] = p.face_id
                    global_to_recognition_method[final_id] = p.recognition_method
                elif final_id in global_to_personnel_map:
                    p.face_id = global_to_personnel_map[final_id]
                    p.recognition_method = global_to_recognition_method[final_id]
                    local_to_personnel_map[(vid_id, p.track_id)] = p.face_id
                    local_to_recognition_method[(vid_id, p.track_id)] = p.recognition_method

                redis_id = global_to_personnel_map.get(final_id, final_id)
                rec_method = global_to_recognition_method.get(final_id) if final_id in global_to_personnel_map else None
                posture = getattr(p, "posture", "standing")

                person_observation = {
                    "id": redis_id, "x": float(round(room_x, 2)), "y": float(room_y), "z": float(round(room_z, 2)),
                    "zone": zone_id, "floor": floor_map[vid_id], "posture": posture,
                    "ppe": _ppe_or_unknown(p.ppe),
                    "confidence": float(round(p.confidence, 2)),
                    "cameras_visible": 1, "camera_ids": [int(vid_id)], "recognition_method": rec_method,
                }

                if redis_id in fused_persons_dict:
                    _merge_person_observation(fused_persons_dict[redis_id], person_observation)
                else:
                    fused_persons_dict[redis_id] = person_observation

        all_persons = list(fused_persons_dict.values())
        label_cache = {}
        for vid_id, tracked in per_video_tracks.items():
            for p in tracked:
                lbl = f"#{p.track_id + global_id_offset[vid_id]}"
                if (vid_id, p.track_id) in local_to_personnel_map:
                    lbl = f"#{local_to_personnel_map[(vid_id, p.track_id)]} ({local_to_recognition_method.get((vid_id, p.track_id), 'face').upper()})"
                elif vid_id != 0:
                    mwa, mai, md = person_matched_info.get((vid_id, p.track_id), (False, None, None))
                    if mwa and md is not None and md < 0.4:
                        if mai in global_to_personnel_map:
                            lbl = f"#{global_to_personnel_map[mai]} ({global_to_recognition_method.get(mai, 'face').upper()})"
                        else:
                            lbl = f"#{mai} (fusion)"
                label_cache[(vid_id, p.track_id)] = lbl

        _write_realtime_state(redis_client, all_persons, zone_defs)

        _publish_annotated_frames(
            frames,
            per_video_tracks,
            local_to_personnel_map,
            local_to_recognition_method,
            global_to_personnel_map,
            global_to_recognition_method,
            upload_queue,
            show_preview,
            global_id_offsets=global_id_offset,
            label_cache=label_cache,
        )
        if show_preview and cv2.waitKey(1) & 0xFF == ord('q'): break

        _evict_stale_tracks(per_video_tracks, local_to_personnel_map, local_to_recognition_method, global_to_personnel_map, global_to_recognition_method, active_global_ids, None)
        frame_count = _finish_frame(redis_client, "video", frame_count, t_start, len(all_persons), max_fps)

    _shutdown_uploader(upload_queue, uploader_thread)
    for cap in caps.values(): cap.release()
    if show_preview: cv2.destroyAllWindows()

def main() -> None:
    parser = argparse.ArgumentParser(description="RigVision-3D Computer Vision Pipeline")
    parser.add_argument("--mode", choices=["demo", "live", "video"], default="demo")
    parser.add_argument("--cameras", nargs="+", default=["0"])
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--model", default="yolov8l.pt")
    parser.add_argument("--show-preview", action="store_true")
    parser.add_argument("--redis-host", default="localhost")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--redis-password", default=None)
    parser.add_argument("--device", default=None)
    parser.add_argument("--resize-width", type=int, default=None)
    parser.add_argument("--max-fps", type=float, default=None)
    parser.add_argument("--floor-map", nargs="+", type=int, default=None)

    args = parser.parse_args()
    cv_dir = os.path.dirname(os.path.abspath(__file__))
    zone_definitions_path = os.path.join(os.path.dirname(cv_dir), "cad", "zone_definitions.json")
    calibration_dir = os.path.join(cv_dir, "calibration", "configs")
    redis_password = args.redis_password or os.getenv("REDIS_PASSWORD") or None

    print(f"[*] Connecting to Redis at {args.redis_host}:{args.redis_port}...")
    redis_client = redis.Redis(host=args.redis_host, port=args.redis_port, password=redis_password, decode_responses=True)
    redis_client.ping()
    print("  [OK] Redis connected\n")

    threading.Thread(target=redis_command_listener, args=(redis_client,), daemon=True).start()

    if args.mode == "demo":
        run_demo_mode(redis_client, zone_definitions_path)
    elif args.mode == "video":
        run_video_mode(
            redis_client=redis_client, video_paths=args.cameras,
            zone_definitions_path=zone_definitions_path, confidence=args.confidence,
            model_path=args.model, show_preview=args.show_preview, device=args.device,
            resize_width=args.resize_width, max_fps=args.max_fps, floor_map=args.floor_map,
        )
    elif args.mode == "live":
        run_live_mode(
            redis_client=redis_client, camera_sources=args.cameras,
            zone_definitions_path=zone_definitions_path, calibration_dir=calibration_dir,
            confidence=args.confidence, model_path=args.model, show_preview=args.show_preview,
            device=args.device, resize_width=args.resize_width, max_fps=args.max_fps, floor_map=args.floor_map,
        )

if __name__ == "__main__":
    main()
