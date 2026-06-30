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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import numpy as np

if TYPE_CHECKING:
    from tracking.cross_camera import MatchedPerson


@dataclass
class CameraCalibration:
    """Calibration data for a single camera.
    
    Loaded from JSON files produced by calibrate_intrinsic.py and calibrate_extrinsic.py.
    
    Attributes:
        camera_id: Integer camera identifier.
        K: 3×3 intrinsic matrix (focal length + principal point).
        dist_coeffs: Distortion coefficients (radial + tangential).
        R: 3×3 rotation matrix (camera → world orientation).
        t: 3×1 translation vector (camera position).
        P: 3×4 projection matrix = K @ [R | t].
        image_size: (width, height) of the camera image.
    """
    camera_id: int
    K: np.ndarray          # 3×3 intrinsic matrix
    dist_coeffs: np.ndarray # distortion coefficients
    R: np.ndarray          # 3×3 rotation matrix
    t: np.ndarray          # 3×1 translation vector
    P: np.ndarray          # 3×4 projection matrix
    image_size: Tuple[int, int]  # (width, height)

    @classmethod
    def from_json(cls, filepath: str, camera_id: int) -> "CameraCalibration":
        """Load calibration from a JSON file.
        
        Expected JSON format:
        {
            "camera_matrix": [[fx, 0, cx], [0, fy, cy], [0, 0, 1]],
            "dist_coeffs": [k1, k2, p1, p2, k3],
            "rotation_matrix": [[r11, r12, r13], ...],
            "translation_vector": [tx, ty, tz],
            "image_size": [width, height]
        }
        """
        with open(filepath, "r") as f:
            data = json.load(f)
        
        K = np.array(data["camera_matrix"], dtype=np.float64)
        dist = np.array(data["dist_coeffs"], dtype=np.float64).flatten()
        R = np.array(data["rotation_matrix"], dtype=np.float64)
        t = np.array(data["translation_vector"], dtype=np.float64).reshape(3, 1)
        image_size = tuple(data.get("image_size", [640, 480]))
        
        # Compute projection matrix: P = K @ [R | t]
        Rt = np.hstack([R, t])  # 3×4
        P = K @ Rt              # 3×4
        
        return cls(
            camera_id=camera_id,
            K=K,
            dist_coeffs=dist,
            R=R,
            t=t,
            P=P,
            image_size=image_size,
        )

    @classmethod
    def create_default(cls, camera_id: int, image_size: Tuple[int, int] = (640, 480)) -> "CameraCalibration":
        """Create a default calibration (no distortion, centered camera).
        
        Used for demo mode or when real calibration isn't available.
        Places camera at the position defined in zone_definitions.json.
        """
        w, h = image_size
        # Approximate focal length: ~600px for a typical phone camera
        fx = fy = 600.0
        cx, cy = w / 2, h / 2
        
        K = np.array([
            [fx,  0, cx],
            [ 0, fy, cy],
            [ 0,  0,  1]
        ], dtype=np.float64)
        
        dist = np.zeros(5, dtype=np.float64)
        R = np.eye(3, dtype=np.float64)
        t = np.zeros((3, 1), dtype=np.float64)
        P = K @ np.hstack([R, t])
        
        return cls(
            camera_id=camera_id,
            K=K,
            dist_coeffs=dist,
            R=R,
            t=t,
            P=P,
            image_size=image_size,
        )


def load_calibrations(configs_dir: str) -> Dict[int, CameraCalibration]:
    """Load all camera calibrations from a directory.
    
    Expects files named camera_0.json, camera_1.json, etc.
    
    Args:
        configs_dir: Path to directory containing calibration JSONs.
    
    Returns:
        Dict mapping camera_id → CameraCalibration.
    """
    calibrations: Dict[int, CameraCalibration] = {}
    
    if not os.path.exists(configs_dir):
        print(f"[triangulation] Calibration dir not found: {configs_dir}")
        return calibrations
    
    for filename in os.listdir(configs_dir):
        if filename.startswith("camera_") and filename.endswith(".json"):
            try:
                cam_id = int(filename.replace("camera_", "").replace(".json", ""))
                filepath = os.path.join(configs_dir, filename)
                calibrations[cam_id] = CameraCalibration.from_json(filepath, cam_id)
                print(f"[triangulation] Loaded calibration for camera {cam_id}")
            except (ValueError, json.JSONDecodeError) as e:
                print(f"[triangulation] Error loading {filename}: {e}")
    
    return calibrations


def triangulate_dlt(
    pt1: Tuple[float, float],
    pt2: Tuple[float, float],
    P1: np.ndarray,
    P2: np.ndarray,
) -> Tuple[float, float, float]:
    """Direct Linear Transform triangulation.
    
    Given a 2D point in camera 1 and a 2D point in camera 2, plus their
    projection matrices, compute the 3D world point.
    
    HOW IT WORKS:
    ─────────────
    Each 2D point (u, v) and its projection matrix P give us 2 equations:
      u = (P[0] @ X) / (P[2] @ X)
      v = (P[1] @ X) / (P[2] @ X)
    
    Rearranging: (u * P[2] - P[0]) @ X = 0  and  (v * P[2] - P[1]) @ X = 0
    
    Two cameras → 4 equations, 3 unknowns → overdetermined system.
    OpenCV solves this with SVD (Singular Value Decomposition).
    
    Args:
        pt1: (x, y) foot point in pixels, camera 1.
        pt2: (x, y) foot point in pixels, camera 2.
        P1: 3×4 projection matrix for camera 1.
        P2: 3×4 projection matrix for camera 2.
    
    Returns:
        (x, y, z) 3D world coordinates in meters.
    """
    # OpenCV expects points as (2, 1) float64 arrays
    pts1 = np.array([[pt1[0]], [pt1[1]]], dtype=np.float64)
    pts2 = np.array([[pt2[0]], [pt2[1]]], dtype=np.float64)
    
    # Triangulate: returns 4D homogeneous coordinates
    import cv2
    point_4d = cv2.triangulatePoints(P1, P2, pts1, pts2)
    
    # Convert from homogeneous: divide by w
    point_3d = point_4d[:3, 0] / point_4d[3, 0]
    
    return (float(point_3d[0]), float(point_3d[1]), float(point_3d[2]))


def compute_reprojection_error(
    point_3d: Tuple[float, float, float],
    pixel: Tuple[float, float],
    P: np.ndarray,
) -> float:
    """How far off is the triangulated point when projected back to 2D?
    
    A good triangulation should reproject very close to the original pixel.
    Error > 10px usually means something went wrong.
    
    Args:
        point_3d: Triangulated (x, y, z) in meters.
        pixel: Original (u, v) detection in pixels.
        P: 3×4 projection matrix.
    
    Returns:
        Reprojection error in pixels.
    """
    X = np.array([point_3d[0], point_3d[1], point_3d[2], 1.0])
    projected = P @ X
    if abs(projected[2]) < 1e-10:
        return float('inf')
    
    u = projected[0] / projected[2]
    v = projected[1] / projected[2]
    
    error = np.sqrt((u - pixel[0])**2 + (v - pixel[1])**2)
    return float(error)


def ground_plane_intersection(
    pixel: Tuple[float, float],
    K: np.ndarray,
    R: np.ndarray,
    t: np.ndarray,
    floor_y: float = 0.0,
) -> Tuple[float, float, float]:
    """Project a pixel onto the ground plane (Y = floor_y).
    
    Used when only one camera sees a person. Less accurate than DLT
    but gives a reasonable estimate.
    
    HOW IT WORKS:
    ─────────────
    1. Convert pixel (u,v) to a ray in camera coordinates:
       ray_cam = K^{-1} @ [u, v, 1]^T
    
    2. Transform ray to world coordinates:
       ray_world = R^T @ ray_cam
    
    3. Camera position in world:
       cam_pos = -R^T @ t
    
    4. Find where the ray hits Y = floor_y:
       cam_pos.y + λ * ray_world.y = floor_y
       λ = (floor_y - cam_pos.y) / ray_world.y
    
    5. 3D position = cam_pos + λ * ray_world
    
    Args:
        pixel: (u, v) foot point in pixels.
        K: 3×3 intrinsic matrix.
        R: 3×3 rotation matrix.
        t: 3×1 translation vector.
        floor_y: Y-coordinate of the floor plane (default 0).
    
    Returns:
        (x, y, z) estimated 3D position on the floor.
    """
    # Step 1: pixel → ray in camera frame
    K_inv = np.linalg.inv(K)
    pixel_h = np.array([pixel[0], pixel[1], 1.0])
    ray_cam = K_inv @ pixel_h
    
    # Step 2: camera frame → world frame
    R_T = R.T
    ray_world = R_T @ ray_cam
    
    # Step 3: camera position in world
    cam_pos = (-R_T @ t).flatten()
    
    # Step 4: intersect with floor plane Y = floor_y
    if abs(ray_world[1]) < 1e-10:
        # Ray is parallel to floor — can't intersect
        # Return camera position projected onto floor
        return (float(cam_pos[0]), floor_y, float(cam_pos[2]))
    
    lam = (floor_y - cam_pos[1]) / ray_world[1]
    
    # Step 5: 3D position
    position = cam_pos + lam * ray_world
    
    return (float(position[0]), floor_y, float(position[2]))


class ZoneAssigner:
    """Determines which zone a 3D point belongs to.
    
    Loads zone bounding boxes from zone_definitions.json and checks
    point-in-box containment.
    """

    def __init__(self, zone_definitions_path: str) -> None:
        """
        Args:
            zone_definitions_path: Path to cad/zone_definitions.json.
        """
        with open(zone_definitions_path, "r") as f:
            data = json.load(f)
        
        self.zones: Dict[str, Dict] = {}
        for zone_id, zone_data in data["zones"].items():
            bounds = zone_data["bounds"]
            self.zones[zone_id] = {
                "name": zone_data["name"],
                "min": (bounds["min"]["x"], bounds["min"]["y"], bounds["min"]["z"]),
                "max": (bounds["max"]["x"], bounds["max"]["y"], bounds["max"]["z"]),
            }
        
        print(f"[triangulation] Loaded {len(self.zones)} zones: {list(self.zones.keys())}")

    def assign(self, x: float, y: float, z: float) -> str:
        """Determine which zone a 3D point is in.
        
        Checks axis-aligned bounding boxes. Returns "unknown" if the
        point is outside all zones.
        
        Args:
            x, y, z: 3D world coordinates in meters.
        
        Returns:
            Zone ID string (e.g., "zone_a", "corridor", "zone_b", "unknown").
        """
        for zone_id, zone in self.zones.items():
            mn = zone["min"]
            mx = zone["max"]
            if (mn[0] <= x <= mx[0] and
                mn[1] <= y <= mx[1] and
                mn[2] <= z <= mx[2]):
                return zone_id
        return "unknown"


class Triangulator:
    """Main triangulation engine.
    
    Takes MatchedPerson objects (from cross-camera matching) and
    computes their 3D positions + zone assignments.
    
    Usage:
        tri = Triangulator(
            calibrations=load_calibrations("cv/calibration/configs"),
            zone_definitions_path="cad/zone_definitions.json",
        )
        persons_3d = tri.triangulate_all(matched_persons)
    """

    def __init__(
        self,
        calibrations: Dict[int, CameraCalibration],
        zone_definitions_path: str,
        reprojection_threshold: float = 15.0,
    ) -> None:
        """
        Args:
            calibrations: Dict of camera_id → CameraCalibration.
            zone_definitions_path: Path to zone_definitions.json.
            reprojection_threshold: Max acceptable reprojection error in pixels.
                                    If DLT error exceeds this, fall back to ground-plane.
        """
        self.calibrations = calibrations
        self.zone_assigner = ZoneAssigner(zone_definitions_path)
        self.reprojection_threshold = reprojection_threshold

    def triangulate_all(
        self, matched_persons: List[MatchedPerson], floor_map: Optional[List[int]] = None
    ) -> List[MatchedPerson]:
        """Compute 3D positions and zone assignments for all matched persons.
        
        For each person:
        - If seen by 2+ cameras with calibration: DLT triangulation
        - If seen by 1 camera with calibration: ground-plane intersection
        - If no calibration available: skip (position stays None)
        
        Modifies MatchedPerson objects in-place (sets position_3d and zone).
        
        Args:
            matched_persons: List of MatchedPerson from cross-camera matching.
            floor_map: Optional list mapping camera/video index to floor index.
        
        Returns:
            Same list with position_3d and zone filled in.
        """
        for person in matched_persons:
            cam_ids = list(person.per_camera.keys())
            calibrated_cams = [c for c in cam_ids if c in self.calibrations]

            if len(calibrated_cams) >= 2:
                # DLT triangulation with first two calibrated cameras
                self._triangulate_dlt(person, calibrated_cams[0], calibrated_cams[1], floor_map)
            elif len(calibrated_cams) == 1:
                # Ground-plane fallback with single camera
                self._ground_plane(person, calibrated_cams[0], floor_map)
            else:
                # No calibration — can't determine 3D position
                person.position_3d = None
                person.zone = "unknown"

            # Assign zone from 3D position
            if person.position_3d is not None:
                x, y, z = person.position_3d
                person.zone = self.zone_assigner.assign(x, y, z)

        return matched_persons

    def _triangulate_dlt(
        self, person: MatchedPerson, cam_a: int, cam_b: int, floor_map: Optional[List[int]] = None
    ) -> None:
        """Triangulate using DLT from two cameras."""
        cal_a = self.calibrations[cam_a]
        cal_b = self.calibrations[cam_b]
        track_a = person.per_camera[cam_a]
        track_b = person.per_camera[cam_b]

        point_3d = triangulate_dlt(
            track_a.foot_point, track_b.foot_point,
            cal_a.P, cal_b.P,
        )

        # Check reprojection error
        error_a = compute_reprojection_error(point_3d, track_a.foot_point, cal_a.P)
        error_b = compute_reprojection_error(point_3d, track_b.foot_point, cal_b.P)
        avg_error = (error_a + error_b) / 2

        if avg_error > self.reprojection_threshold:
            # DLT result is unreliable — fall back to ground-plane
            # using the camera with lower individual error
            if error_a <= error_b:
                self._ground_plane(person, cam_a, floor_map)
            else:
                self._ground_plane(person, cam_b, floor_map)
        else:
            person.position_3d = point_3d

    def _ground_plane(self, person: MatchedPerson, cam_id: int, floor_map: Optional[List[int]] = None) -> None:
        """Estimate position via ground-plane intersection."""
        cal = self.calibrations[cam_id]
        track = person.per_camera[cam_id]

        floor_y = 0.0
        if floor_map is not None and cam_id < len(floor_map):
            floor_y = floor_map[cam_id] * 3.0

        position = ground_plane_intersection(
            track.foot_point, cal.K, cal.R, cal.t, floor_y=floor_y
        )
        person.position_3d = position
