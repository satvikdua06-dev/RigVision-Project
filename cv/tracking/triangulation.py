"""
RigVision-3D — 3D Triangulation & Per-Zone Calibration
=======================================================

PURE, IN-PROCESS triangulation utilities used directly by cv/pipeline.py.

Previously this file was a standalone Kafka micro-service (consume "ccm-matches",
produce "3d-locations"). That stage was redundant — its logic is pure math that the
pipeline can call in-process — so the Kafka service was removed. What remains:

  - CameraCalibration : intrinsics (K, dist) + extrinsics (R, t) + projection P
  - triangulate_dlt   : two 2D foot-points + two P matrices  -> one 3D point (DLT)
  - compute_reprojection_avg : reproject a 3D point and measure pixel error (a gate)
  - ZoneCalib + load_zone_calibrations : load per-zone-group calibration from
        cv/calibration/configs/ (produced by calibrate_intrinsic.py /
        calibrate_extrinsic.py), falling back to a synthetic stereo rig so the
        pipeline runs before any real calibration exists.

KEY DESIGN — zones come from camera GROUPS, not from a global world frame
─────────────────────────────────────────────────────────────────────────
Each zone owns exactly two overlapping cameras (Room A = cam0+cam1, Room B = cam2+cam3).
We triangulate each zone's pair INDEPENDENTLY, in that pair's own local frame (the
master camera is the origin). Because we already know which zone a camera pair belongs
to, the person's ZONE is decided by *which group saw them* — we never need a single
world frame shared across all four cameras, and we never run a bounding-box test to
guess the zone. The triangulated point is only used to place the avatar *inside* that
known room for display.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import cv2


LOG_PREFIX = "[triangulation]"


# ── Single-camera calibration ─────────────────────────────────────────────────
@dataclass
class CameraCalibration:
    """Everything needed to project between this camera's pixels and 3D points.

    K            : 3x3 intrinsic matrix (focal lengths + principal point).
    dist_coeffs  : lens distortion coefficients.
    R, t         : extrinsic pose of this camera *relative to its zone's master
                   camera*. The master camera has R = I, t = 0 (it defines the
                   zone-local frame); the second camera carries the stereo R, t.
    P            : 3x4 projection matrix P = K @ [R | t], the thing triangulation needs.
    image_size   : (width, height) the intrinsics were calibrated at.
    """
    camera_id: int
    K: np.ndarray
    dist_coeffs: np.ndarray
    R: np.ndarray
    t: np.ndarray
    P: np.ndarray
    image_size: Tuple[int, int]

    @classmethod
    def create_default(cls, camera_id: int, image_size: Tuple[int, int] = (640, 480)) -> "CameraCalibration":
        """A reasonable synthetic camera (used when no real intrinsics exist yet)."""
        w, h = image_size
        fx = fy = 600.0                      # plausible focal length for a phone at 640px
        cx, cy = w / 2.0, h / 2.0            # principal point at image centre
        K = np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64)
        dist = np.zeros(5, dtype=np.float64)
        R = np.eye(3, dtype=np.float64)
        t = np.zeros((3, 1), dtype=np.float64)
        P = K @ np.hstack([R, t])
        return cls(camera_id, K, dist, R, t, P, image_size)

    def with_pose(self, R: np.ndarray, t: np.ndarray) -> "CameraCalibration":
        """Return a copy of this calibration with a new extrinsic pose (recomputing P)."""
        R = np.asarray(R, dtype=np.float64).reshape(3, 3)
        t = np.asarray(t, dtype=np.float64).reshape(3, 1)
        P = self.K @ np.hstack([R, t])
        return CameraCalibration(self.camera_id, self.K, self.dist_coeffs, R, t, P, self.image_size)


# ── Per-zone calibration bundle ───────────────────────────────────────────────
@dataclass
class ZoneCalib:
    """Calibration for one zone's camera pair.

    zone_id    : "zone_a" / "zone_b".
    master_id  : the camera that defines the zone-local origin (R=I, t=0).
    cameras    : {camera_id: CameraCalibration} for both cameras in the zone.
    fundamental: {(cam_a, cam_b): F} fundamental matrix for the pair, used by
                 cross-camera matching's epipolar fallback. Keyed by sorted ids.
    is_real    : True if loaded from real .npz configs, False if synthetic fallback.
    """
    zone_id: str
    master_id: int
    cameras: Dict[int, CameraCalibration]
    fundamental: Dict[Tuple[int, int], np.ndarray] = field(default_factory=dict)
    is_real: bool = False


# ── Core math ─────────────────────────────────────────────────────────────────
def triangulate_dlt(pt1: Tuple[float, float], pt2: Tuple[float, float],
                    P1: np.ndarray, P2: np.ndarray) -> Tuple[float, float, float]:
    """Direct Linear Transform triangulation of one point seen by two cameras.

    Given the same physical point imaged at pt1 (camera 1) and pt2 (camera 2), plus
    each camera's projection matrix, recover the single 3D point that projects to both.
    cv2.triangulatePoints returns homogeneous (X, Y, Z, W); we divide by W to normalise.
    """
    pts1 = np.array([[pt1[0]], [pt1[1]]], dtype=np.float64)
    pts2 = np.array([[pt2[0]], [pt2[1]]], dtype=np.float64)
    point_4d = cv2.triangulatePoints(P1, P2, pts1, pts2)
    if point_4d.shape[0] < 4 or abs(point_4d[3, 0]) < 1e-12:
        raise RuntimeError("Degenerate triangulation result")
    point_3d = point_4d[:3, 0] / point_4d[3, 0]
    return float(point_3d[0]), float(point_3d[1]), float(point_3d[2])


def compute_reprojection_avg(point_3d: Tuple[float, float, float],
                             cam_a: CameraCalibration, cam_b: CameraCalibration,
                             pt_a: Tuple[float, float], pt_b: Tuple[float, float]) -> float:
    """Project a triangulated 3D point back into both cameras and average the pixel
    error vs. the observed foot-points. A large error means the two cameras were
    matched to *different* people, so the pipeline discards that 3D fix."""
    rvec_a, _ = cv2.Rodrigues(cam_a.R)
    rvec_b, _ = cv2.Rodrigues(cam_b.R)
    obj = np.array(point_3d, dtype=np.float64).reshape((1, 1, 3))

    imgpts_a, _ = cv2.projectPoints(obj, rvec_a, cam_a.t.reshape(3, 1), cam_a.K, cam_a.dist_coeffs)
    imgpts_b, _ = cv2.projectPoints(obj, rvec_b, cam_b.t.reshape(3, 1), cam_b.K, cam_b.dist_coeffs)

    pa = imgpts_a.reshape(-1, 2)[0]
    pb = imgpts_b.reshape(-1, 2)[0]
    err_a = float(np.linalg.norm(np.array(pt_a) - pa))
    err_b = float(np.linalg.norm(np.array(pt_b) - pb))
    return (err_a + err_b) / 2.0


# ── Calibration loading ───────────────────────────────────────────────────────
def _load_intrinsics(configs_dir: str, cam_id: int, target_width: Optional[int] = None) -> Optional[CameraCalibration]:
    """Load intrinsics_cam_{id}.npz (written by calibrate_intrinsic.py) if present,
    scaling parameters to match runtime target_width if specified."""
    path = os.path.join(configs_dir, f"intrinsics_cam_{cam_id}.npz")
    if not os.path.exists(path):
        return None
    try:
        with np.load(path) as data:
            K = np.asarray(data["camera_matrix"], dtype=np.float64)
            dist = np.asarray(data["dist_coeffs"], dtype=np.float64).ravel()
        # image_size isn't stored by the intrinsic script; principal point ≈ centre,
        # so (2*cx, 2*cy) recovers the calibration resolution well enough for our use.
        w = int(round(2 * K[0, 2])) or 640
        h = int(round(2 * K[1, 2])) or 480
        
        if target_width is not None and target_width != w:
            scale = target_width / w
            K = K.copy()
            K[0, 0] *= scale  # fx
            K[1, 1] *= scale  # fy
            K[0, 2] *= scale  # cx
            K[1, 2] *= scale  # cy
            w = target_width
            h = int(round(h * scale))
            
        cam = CameraCalibration.create_default(cam_id, (w, h))
        return CameraCalibration(cam_id, K, dist, cam.R, cam.t, K @ np.hstack([cam.R, cam.t]), (w, h))
    except Exception as e:
        print(f"{LOG_PREFIX} failed to load intrinsics for cam {cam_id}: {e}")
        return None


def _load_extrinsics(configs_dir: str, master_id: int, target_id: int, target_width: Optional[int] = None):
    """Load extrinsics_{master}_to_{target}.npz (R, t, F) if present,
    scaling the fundamental matrix F to match target_width if specified."""
    path = os.path.join(configs_dir, f"extrinsics_{master_id}_to_{target_id}.npz")
    if not os.path.exists(path):
        return None
    try:
        with np.load(path) as data:
            R = np.asarray(data["R"], dtype=np.float64).reshape(3, 3)
            T = np.asarray(data["T"], dtype=np.float64).reshape(3, 1)
            F = np.asarray(data["F"], dtype=np.float64).reshape(3, 3) if "F" in data else None
            
        if target_width is not None and F is not None:
            master_path = os.path.join(configs_dir, f"intrinsics_cam_{master_id}.npz")
            if os.path.exists(master_path):
                with np.load(master_path) as m_data:
                    K_master = np.asarray(m_data["camera_matrix"], dtype=np.float64)
                orig_w = int(round(2 * K_master[0, 2])) or 640
                if orig_w != target_width:
                    scale = target_width / orig_w
                    S_inv = np.array([
                        [1.0 / scale, 0.0, 0.0],
                        [0.0, 1.0 / scale, 0.0],
                        [0.0, 0.0, 1.0]
                    ], dtype=np.float64)
                    F = S_inv.T @ F @ S_inv
        return R, T, F
    except Exception as e:
        print(f"{LOG_PREFIX} failed to load extrinsics {master_id}->{target_id}: {e}")
        return None


def _synthetic_zone_calib(zone_id: str, cam_ids: List[int], target_width: Optional[int] = None) -> ZoneCalib:
    """A working stereo pair when no real calibration exists yet: identical default
    intrinsics, the second camera shifted 0.5 m along X to provide parallax, and a
    fundamental matrix derived from that synthetic geometry. Triangulation will be
    only roughly metric, but the pipeline runs end-to-end and zone tagging is exact."""
    master_id, target_id = cam_ids[0], cam_ids[1]
    w = target_width or 640
    h = int(round(w * 0.75))  # fallback to 4:3 aspect ratio
    master = CameraCalibration.create_default(master_id, (w, h))               # R=I, t=0 (origin)
    R = np.eye(3, dtype=np.float64)
    t = np.array([[0.5], [0.0], [0.0]], dtype=np.float64)              # 0.5 m baseline
    target = CameraCalibration.create_default(target_id, (w, h)).with_pose(R, t)

    # Fundamental matrix for the synthetic pair: F = K_b^-T [t]_x R K_a^-1.
    tx = np.array([[0, -t[2, 0], t[1, 0]],
                   [t[2, 0], 0, -t[0, 0]],
                   [-t[1, 0], t[0, 0], 0]], dtype=np.float64)
    E = tx @ R
    F = np.linalg.inv(target.K).T @ E @ np.linalg.inv(master.K)

    key = (min(master_id, target_id), max(master_id, target_id))
    return ZoneCalib(zone_id=zone_id, master_id=master_id,
                     cameras={master_id: master, target_id: target},
                     fundamental={key: F}, is_real=False)


def load_zone_calibrations(zone_groups: Dict[str, List[int]],
                           configs_dir: str,
                           target_width: Optional[int] = None) -> Dict[str, ZoneCalib]:
    """Build a ZoneCalib for every zone group, scaling cameras/fundamentals to target_width.

    For each zone (e.g. "zone_a": [0, 1]):
      1. Load real intrinsics for both cameras and the stereo extrinsics for the pair.
      2. If everything is present, build real P matrices (master at origin, second
         camera at the calibrated R, t) and use the calibrated fundamental matrix.
      3. If anything is missing, fall back to a synthetic stereo rig for that zone so
         the pipeline still runs — the moment you drop the real .npz files into
         configs_dir, that zone automatically switches to real calibration.

    The two cameras of a zone are NEVER mixed with another zone's cameras, so the
    "first two cameras" assumption downstream is always safe.
    """
    out: Dict[str, ZoneCalib] = {}
    for zone_id, cam_ids in zone_groups.items():
        if len(cam_ids) < 2:
            # A zone with a single camera can't be stereo-triangulated; skip calib.
            print(f"{LOG_PREFIX} zone {zone_id} has <2 cameras; no stereo calibration")
            continue
        master_id, target_id = cam_ids[0], cam_ids[1]

        master = _load_intrinsics(configs_dir, master_id, target_width)
        target = _load_intrinsics(configs_dir, target_id, target_width)
        extr = _load_extrinsics(configs_dir, master_id, target_id, target_width)

        if master is None or target is None or extr is None:
            out[zone_id] = _synthetic_zone_calib(zone_id, cam_ids, target_width)
            print(f"{LOG_PREFIX} zone {zone_id}: using SYNTHETIC calibration "
                  f"(missing real configs for cams {master_id}/{target_id})")
            continue

        R, T, F = extr
        master = master.with_pose(np.eye(3), np.zeros((3, 1)))   # master defines origin
        target = target.with_pose(R, T)                          # second cam relative to it
        key = (min(master_id, target_id), max(master_id, target_id))
        out[zone_id] = ZoneCalib(zone_id=zone_id, master_id=master_id,
                                 cameras={master_id: master, target_id: target},
                                 fundamental={key: F} if F is not None else {},
                                 is_real=True)
        print(f"{LOG_PREFIX} zone {zone_id}: using REAL calibration for cams {master_id}/{target_id}")
    return out
