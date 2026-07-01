"""
RigVision-3D — 3D Triangulation & Zone Assignment
===================================================

Converts 2D pixel coordinates from cameras into 3D world positions.

TWO METHODS:
────────────
1. DLT TRIANGULATION (2+ cameras see the same person):
   Given a 2D point in camera 1 and a 2D point in camera 2 (plus
   calibration data for both cameras), compute the unique 3D point
   that projects to both 2D points.
   
   Math: Each 2D point gives 2 equations. Two cameras → 4 equations,
   3 unknowns (X, Y, Z). Overdetermined → solve via SVD (least squares).
   
   OpenCV does this in one call:
     point_4d = cv2.triangulatePoints(P1, P2, pt1, pt2)
     point_3d = point_4d[:3] / point_4d[3]  # normalize homogeneous coords

2. GROUND-PLANE INTERSECTION (1 camera sees the person):
   Cast a ray from the camera through the foot-point pixel into 3D space.
   Where does that ray hit the floor (Y=0)? That's our 3D position.
   
   Math: 
     ray_direction = R^T @ K^{-1} @ [u, v, 1]^T  (pixel → camera → world)
     ray_origin = -R^T @ t                          (camera position in world)
     Find λ such that (ray_origin + λ * ray_direction).y = 0
     position = ray_origin + λ * ray_direction

PROJECTION MATRIX:
──────────────────
P = K @ [R | t]   (3×4 matrix)

Where:
  K = intrinsic matrix (focal length, principal point) — from checkerboard calibration
  R = rotation matrix (camera orientation) — from ArUco extrinsic calibration
  t = translation vector (camera position) — from ArUco extrinsic calibration

The projection matrix P maps 3D world points → 2D pixel points:
  [u, v, w]^T = P @ [X, Y, Z, 1]^T
  pixel = (u/w, v/w)

Triangulation is the INVERSE: given pixels, find the 3D point.
"""

from __future__ import annotations
import json
import os
import signal
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from kafka import KafkaConsumer, KafkaProducer
import cv2


LOG_PREFIX = "[triangulation]"


@dataclass
class CameraCalibration:
    camera_id: int
    K: np.ndarray
    dist_coeffs: np.ndarray
    R: np.ndarray
    t: np.ndarray
    P: np.ndarray
    image_size: Tuple[int, int]

    @classmethod
    def create_default(cls, camera_id: int, image_size: Tuple[int, int] = (640, 480)) -> "CameraCalibration":
        w, h = image_size
        fx = fy = 600.0
        cx, cy = w / 2.0, h / 2.0
        K = np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64)
        dist = np.zeros(5, dtype=np.float64)
        R = np.eye(3, dtype=np.float64)
        t = np.zeros((3, 1), dtype=np.float64)
        P = K @ np.hstack([R, t])
        return cls(camera_id, K, dist, R, t, P, image_size)


def mock_calibrations() -> Dict[int, CameraCalibration]:
    """Return a pair of mock calibrations for camera 0 and 1.

    Camera 1 is translated slightly along X to provide parallax.
    """
    cal0 = CameraCalibration.create_default(0)
    cal1 = CameraCalibration.create_default(1)
    # Put camera 1 half a meter to the right (world coords)
    cal1.t = np.array([[0.5], [0.0], [0.0]], dtype=np.float64)
    cal1.P = cal1.K @ np.hstack([cal1.R, cal1.t])
    return {0: cal0, 1: cal1}


def triangulate_dlt(pt1: Tuple[float, float], pt2: Tuple[float, float], P1: np.ndarray, P2: np.ndarray) -> Tuple[float, float, float]:
    pts1 = np.array([[pt1[0]], [pt1[1]]], dtype=np.float64)
    pts2 = np.array([[pt2[0]], [pt2[1]]], dtype=np.float64)
    point_4d = cv2.triangulatePoints(P1, P2, pts1, pts2)
    if point_4d.shape[0] < 4 or abs(point_4d[3, 0]) < 1e-12:
        raise RuntimeError("Degenerate triangulation result")
    point_3d = point_4d[:3, 0] / point_4d[3, 0]
    return float(point_3d[0]), float(point_3d[1]), float(point_3d[2])


def compute_reprojection_avg(point_3d: Tuple[float, float, float], cam_a: CameraCalibration, cam_b: CameraCalibration, pt_a: Tuple[float, float], pt_b: Tuple[float, float]) -> float:
    # Convert rotation matrices to rotation vectors
    rvec_a, _ = cv2.Rodrigues(cam_a.R)
    rvec_b, _ = cv2.Rodrigues(cam_b.R)
    tvec_a = cam_a.t.reshape(3, 1)
    tvec_b = cam_b.t.reshape(3, 1)

    obj = np.array(point_3d, dtype=np.float64).reshape((1, 1, 3)) # converting to shape (1, 1, 3) for projectPoints

    imgpts_a, _ = cv2.projectPoints(obj, rvec_a, tvec_a, cam_a.K, cam_a.dist_coeffs)
    imgpts_b, _ = cv2.projectPoints(obj, rvec_b, tvec_b, cam_b.K, cam_b.dist_coeffs)

    pa = imgpts_a.reshape(-1, 2)[0] # reshape to (N, 2) and take first point
    pb = imgpts_b.reshape(-1, 2)[0]

    err_a = float(np.linalg.norm(np.array(pt_a) - pa))
    err_b = float(np.linalg.norm(np.array(pt_b) - pb))
    return (err_a + err_b) / 2.0


class TriangulationService:
    def __init__(self, bootstrap_servers: Optional[List[str]] = None, topic_in: str = "ccm-matches", topic_out: str = "3d-locations"):
        self.bootstrap_servers = bootstrap_servers or [os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")]
        self.topic_in = topic_in
        self.topic_out = topic_out
        self.running = True
        self.calibrations = mock_calibrations()
        self.reproj_threshold = float(os.environ.get("REPROJ_THRESHOLD", "15.0"))

        try:
            self.consumer = KafkaConsumer(
                self.topic_in,
                bootstrap_servers=self.bootstrap_servers,
                group_id="rigvision-3d-consumer-group",
                auto_offset_reset="latest",
                enable_auto_commit=True,
                value_deserializer=lambda v: v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else v,
                consumer_timeout_ms=1000,
            )

            self.producer = KafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
        except Exception as exc:
            raise RuntimeError(
                f"Kafka is not reachable at {', '.join(self.bootstrap_servers)}. "
                "Start Kafka first, then rerun with KAFKA_BOOTSTRAP_SERVERS set correctly."
            ) from exc

    def shutdown(self):
        self.running = False
        try:
            self.consumer.close()
        except Exception:
            pass
        try:
            self.producer.close()
        except Exception:
            pass

    def process_message(self, payload: dict) -> Optional[dict]:
        # Validate schema
        if not payload or "matched_persons" not in payload:
            return None

        out = {"timestamp": payload.get("timestamp", time.time()), "matched_persons": []}

        for person in payload.get("matched_persons", []):
            try:
                per_camera = person.get("per_camera", {})
                cams = sorted(per_camera.keys())
                # need at least two cameras
                if len(cams) < 2:
                    # skip or attempt ground-plane fallback; here skip
                    out_person = dict(person)
                    out["matched_persons"].append(out_person)
                    continue

                # pick first two cameras
                cam0_key, cam1_key = cams[0], cams[1]
                cam0_id = int(cam0_key.replace("cam_", "")) if cam0_key.startswith("cam_") else int(cam0_key)
                cam1_id = int(cam1_key.replace("cam_", "")) if cam1_key.startswith("cam_") else int(cam1_key)

                cam0 = self.calibrations.get(cam0_id)
                cam1 = self.calibrations.get(cam1_id)
                if cam0 is None or cam1 is None:
                    out_person = dict(person)
                    out["matched_persons"].append(out_person)
                    continue

                pt0 = tuple(per_camera[cam0_key]["foot_point"])
                pt1 = tuple(per_camera[cam1_key]["foot_point"])

                # Triangulate
                try:
                    position_3d = triangulate_dlt(pt0, pt1, cam0.P, cam1.P)
                except Exception as e:
                    # drop this person silently
                    out_person = dict(person)
                    out["matched_persons"].append(out_person)
                    continue

                # Reprojection validation
                try:
                    avg_err = compute_reprojection_avg(position_3d, cam0, cam1, pt0, pt1)
                except Exception:
                    avg_err = float("inf")

                if avg_err < self.reproj_threshold:
                    out_person = dict(person)
                    out_person["position_3d"] = [float(position_3d[0]), float(position_3d[1]), float(position_3d[2])]
                    out_person["reprojection_error"] = float(avg_err)
                    out["matched_persons"].append(out_person)
                else:
                    # drop the position for this person (per spec, silently)
                    out_person = dict(person)
                    out["matched_persons"].append(out_person)

            except Exception:
                out_person = dict(person)
                out["matched_persons"].append(out_person)

        return out

    def run(self):
        print(f"{LOG_PREFIX} Starting triangulation service; consuming {self.topic_in}")
        while self.running:
            try:
                for msg in self.consumer:
                    if not self.running:
                        break
                    raw = msg.value
                    try:
                        payload = json.loads(raw)
                        print(f"{LOG_PREFIX} Received raw payload: {raw}")
                    except Exception:
                        # skip malformed JSON
                        continue

                    enriched = self.process_message(payload)
                    if enriched is not None:
                        try:
                            self.producer.send(self.topic_out, enriched)
                            self.producer.flush()
                            print(f"{LOG_PREFIX} Published enriched payload to {self.topic_out}")
                        except Exception:
                            print(f"{LOG_PREFIX} Failed to publish enriched payload")
                            # best-effort produce; continue
                            pass

                # consumer timed out without messages; sleep briefly
                time.sleep(0.1)
            except KeyboardInterrupt:
                break
            except Exception:
                # keep service alive on unexpected exceptions
                time.sleep(0.5)


def main():
    if cv2 is None:
        print(f"{LOG_PREFIX} OpenCV not available. Exiting.")
        sys.exit(1)

    servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    bootstrap = [s.strip() for s in servers.split(",") if s.strip()]

    try:
        svc = TriangulationService(bootstrap_servers=bootstrap)
    except RuntimeError as exc:
        print(f"{LOG_PREFIX} {exc}")
        sys.exit(1)

    def _handle(sig, frame):
        print(f"{LOG_PREFIX} Received signal {sig}, shutting down")
        svc.shutdown()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    try:
        svc.run()
    finally:
        svc.shutdown()


if __name__ == "__main__":
    main()