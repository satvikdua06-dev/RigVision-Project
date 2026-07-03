"""
RigVision-3D — Cross-Camera Matching Utilities
==============================================

Pure utility functions for matching tracked persons across multiple cameras.

MATCHING STRATEGY:
──────────────────
1. ArUco Identity (strongest signal):
   If two tracklets from different cameras see the same physical ArUco marker,
   they are the same person globally.

2. Epipolar Geometry (spatial constraint):
   If two tracklets see points related by the fundamental matrix between cameras,
   they are likely the same person.

3. Appearance Similarity (visual signal):
   If two tracklets look similar (ReID embeddings or aspect ratio),
   they are more likely to be the same person.

Output: Groups of tracklets matched across cameras as MatchedPerson records.

CALLER OWNS:
────────────
- Fundamental matrices
- Matching state (previous_matches, aruco_matches, next_global_id)
- All orchestration and frame-to-frame logic

This module contains only stateless utility functions.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    from scipy.optimize import linear_sum_assignment
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tracking.tracker import TrackedPerson


def MatchedPerson(
    global_id: int,
    per_camera: Dict[int, TrackedPerson],
    position_3d: Optional[Tuple[float, float, float]] = None,
    zone: Optional[str] = None,
) -> SimpleNamespace:
    """A person matched across multiple cameras.
    
    Attributes:
        global_id: Unique ID across all cameras. For ArUco matches, this is
                   the physical marker ID; fallback IDs start at 100000.
        per_camera: Dict mapping camera_id → TrackedPerson from that camera.
        position_3d: Triangulated 3D position (x, y, z) in meters. None if not yet triangulated.
        zone: Which zone this person is in. None if not yet assigned.
    """
    return SimpleNamespace(
        global_id=global_id,
        per_camera=per_camera,
        position_3d=position_3d,
        zone=zone,
    )


def compute_epipolar_distance(
    pt1: Tuple[float, float],
    pt2: Tuple[float, float],
    F: Optional[np.ndarray] = None,
) -> float:
    """Compute epipolar distance between two points.
    
    WHAT IS EPIPOLAR GEOMETRY?
    ──────────────────────────
    When two cameras look at the same 3D point:
    - Camera 1 sees it at pixel (u1, v1)
    - Camera 2 sees it at pixel (u2, v2)
    
    The Fundamental Matrix F encodes the geometry between the cameras.
    For a correct match: pt2^T × F × pt1 ≈ 0
    
    The distance from this constraint tells us how likely two points
    are to be the same 3D point.
    
    Args:
        pt1: (x, y) pixel coordinates in camera 1.
        pt2: (x, y) pixel coordinates in camera 2.
        F: 3×3 Fundamental matrix. If None, falls back to simple heuristic.
    
    Returns:
        Distance value. Lower = more likely the same person.
    """
    if F is not None:
        # Proper epipolar distance
        p1 = np.array([pt1[0], pt1[1], 1.0])
        p2 = np.array([pt2[0], pt2[1], 1.0])
        
        # Epipolar line in camera 2: l2 = F @ p1
        l2 = F @ p1
        
        # Distance from p2 to epipolar line l2
        # d = |p2^T @ l2| / sqrt(l2[0]^2 + l2[1]^2)
        numerator = abs(p2 @ l2)
        denominator = np.sqrt(l2[0]**2 + l2[1]**2)
        
        return float(numerator / denominator) if denominator > 0 else float('inf')
    else:
        # Fallback: simple Y-coordinate similarity
        # Assumption: cameras are roughly at the same height
        # So the same person should have similar Y-coordinates (foot position)
        return abs(pt1[1] - pt2[1])


def compute_appearance_distance(
    person_a: TrackedPerson,
    person_b: TrackedPerson,
) -> float:
    """Compute appearance distance (disabled).
    
    Appearance-based matching (ReID, aspect ratio) is disabled.
    Cross-camera matching relies solely on ArUco identity and epipolar geometry.
    
    Args:
        person_a: TrackedPerson from camera A.
        person_b: TrackedPerson from camera B.
    
    Returns:
        0.0 (no contribution to matching cost).
    """
    return 0.0


def match_cross_camera(
    per_camera_tracks: Dict[int, List[TrackedPerson]],
    matching_state: Dict,
    fundamental_matrices: Optional[Dict[Tuple[int, int], np.ndarray]] = None,
    epipolar_weight: float = 1.0,
    appearance_weight: float = 0.0,
    max_distance: float = 100.0,
) -> List[MatchedPerson]:

    if fundamental_matrices is None:
        fundamental_matrices = {}

    camera_ids = sorted(per_camera_tracks.keys())

    if len(camera_ids) == 0:
        return []

    # Prune stale tracks from history (older than 10.0 seconds) to prevent ID reuse collisions
    import time
    now = time.time()
    last_seen = matching_state.setdefault("last_seen", {})
    previous_matches = matching_state.setdefault("previous_matches", {})
    stale_keys = [k for k, last_t in last_seen.items() if now - last_t > 10.0]
    for k in stale_keys:
        last_seen.pop(k, None)
        previous_matches.pop(k, None)

    # Set to ensure that every returned MatchedPerson has a strictly unique global_id in the current frame
    assigned_in_frame = set()

    if len(camera_ids) == 1:
        return _single_camera_output(
            matching_state,
            camera_ids[0],
            per_camera_tracks[camera_ids[0]],
            assigned_in_frame
        )

    all_matched = []
    used_tracks = {cam_id: set() for cam_id in camera_ids}

    # ── Pass 1: ArUco identity ────────────────────────────────────────────────
    # Build a simple dict: aruco_id → {cam_id: track}
    # One track per camera per aruco_id — no duplicate handling needed.

    aruco_groups = {}
    for cam_id in camera_ids:
        for track in per_camera_tracks[cam_id]:
            if track.aruco_id is None:
                continue
            if track.aruco_id not in aruco_groups:
                aruco_groups[track.aruco_id] = {}
            aruco_groups[track.aruco_id][cam_id] = track

    for aruco_id, per_camera in aruco_groups.items():
        global_id = _get_or_create_aruco_global_id(matching_state, aruco_id, per_camera, assigned_in_frame)
        all_matched.append(MatchedPerson(global_id=global_id, per_camera=per_camera))
        for cam_id, track in per_camera.items():
            used_tracks[cam_id].add(track.track_id)

    # ── Pass 2: Epipolar fallback ─────────────────────────────────────────────
    # Only runs on tracks that were not matched by ArUco above.
    # Only runs between camera pairs that have a fundamental matrix.

    for i, cam_a in enumerate(camera_ids):
        for cam_b in camera_ids[i + 1:]:

            F = fundamental_matrices.get((cam_a, cam_b))
            if F is None:
                continue

            tracks_a = [t for t in per_camera_tracks[cam_a] if t.track_id not in used_tracks[cam_a]]
            tracks_b = [t for t in per_camera_tracks[cam_b] if t.track_id not in used_tracks[cam_b]]

            if not tracks_a or not tracks_b:
                continue

            matches = _match_pair(tracks_a, tracks_b, F, epipolar_weight, appearance_weight, max_distance)

            for track_a, track_b in matches:
                global_id = _get_or_create_global_id(
                    matching_state, cam_a, track_a.track_id, cam_b, track_b.track_id, assigned_in_frame
                )
                all_matched.append(MatchedPerson(
                    global_id=global_id,
                    per_camera={cam_a: track_a, cam_b: track_b},
                ))
                used_tracks[cam_a].add(track_a.track_id)
                used_tracks[cam_b].add(track_b.track_id)

    # ── Pass 3: Singletons ────────────────────────────────────────────────────
    # Any track not matched in pass 1 or 2 gets its own global_id.

    for cam_id in camera_ids:
        for track in per_camera_tracks[cam_id]:
            if track.track_id in used_tracks[cam_id]:
                continue
            if track.aruco_id is not None:
                global_id = _get_or_create_aruco_global_id(
                    matching_state, track.aruco_id, {cam_id: track}, assigned_in_frame
                )
            else:
                global_id = _get_or_create_global_id(
                    matching_state, cam_id, track.track_id, assigned_in_frame=assigned_in_frame
                )
            all_matched.append(MatchedPerson(
                global_id=global_id,
                per_camera={cam_id: track},
            ))

    return all_matched


def _match_pair(
    tracks_a: List[TrackedPerson],
    tracks_b: List[TrackedPerson],
    F: Optional[np.ndarray],
    epipolar_weight: float = 0.7,
    appearance_weight: float = 0.3,
    max_distance: float = 100.0,
) -> List[Tuple[TrackedPerson, TrackedPerson]]:
    """Match unmatched tracks between two cameras using fallback cost + Hungarian."""
    if not SCIPY_AVAILABLE:
        return []

    n_a = len(tracks_a)
    n_b = len(tracks_b)
    cost_matrix = np.full((n_a, n_b), max_distance)

    for i, ta in enumerate(tracks_a):
        for j, tb in enumerate(tracks_b):
            epi_dist = compute_epipolar_distance(ta.foot_point, tb.foot_point, F)
            app_dist = compute_appearance_distance(ta, tb)
            cost_matrix[i][j] = (
                epipolar_weight * epi_dist +
                appearance_weight * app_dist
            )

    row_idx, col_idx = linear_sum_assignment(cost_matrix)

    matches = []
    for r, c in zip(row_idx, col_idx):
        if cost_matrix[r][c] < max_distance:
            matches.append((tracks_a[r], tracks_b[c]))

    return matches



def _single_camera_output(
    matching_state: Dict,
    cam_id: int,
    tracks: List[TrackedPerson],
    assigned_in_frame: Set[int],
) -> List[MatchedPerson]:
    """Convert one-camera tracks to global records when no cross-camera match is possible."""
    result = []
    for track in tracks:
        if track.aruco_id is not None:
            global_id = _get_or_create_aruco_global_id(
                matching_state, track.aruco_id, {cam_id: track}, assigned_in_frame
            )
        else:
            global_id = _get_or_create_global_id(
                matching_state, cam_id, track.track_id, assigned_in_frame=assigned_in_frame
            )
        result.append(MatchedPerson(
            global_id=global_id,
            per_camera={cam_id: track},
        ))
    return result



def _get_or_create_global_id(
    matching_state: Dict,
    cam_id: int,
    track_id: int,
    cam_id2: Optional[int] = None,
    track_id2: Optional[int] = None,
    assigned_in_frame: Optional[Set[int]] = None,
) -> int:
    """Get or create a fallback global ID for tracks without ArUco identity."""
    if assigned_in_frame is None:
        assigned_in_frame = set()

    key = (cam_id, track_id)
    previous_matches = matching_state.setdefault("previous_matches", {})
    last_seen = matching_state.setdefault("last_seen", {})
    import time
    now = time.time()
    
    # 1. Try to find a valid global_id from history that is NOT already assigned in this frame
    global_id = None
    if key in previous_matches:
        candidate = previous_matches[key]
        if candidate not in assigned_in_frame:
            global_id = candidate
            
    if global_id is None and cam_id2 is not None and (cam_id2, track_id2) in previous_matches:
        candidate = previous_matches[(cam_id2, track_id2)]
        if candidate not in assigned_in_frame:
            global_id = candidate

    # 2. If no valid historical ID exists (or it's already assigned in this frame), generate a new one
    if global_id is None:
        while True:
            candidate = matching_state.setdefault("next_global_id", 100000)
            matching_state["next_global_id"] = candidate + 1
            if candidate not in assigned_in_frame:
                global_id = candidate
                break

    # 3. Update history and return
    previous_matches[(cam_id, track_id)] = global_id
    last_seen[(cam_id, track_id)] = now
    if cam_id2 is not None and track_id2 is not None:
        previous_matches[(cam_id2, track_id2)] = global_id
        last_seen[(cam_id2, track_id2)] = now

    assigned_in_frame.add(global_id)
    return global_id


def _get_or_create_aruco_global_id(
    matching_state: Dict,
    aruco_id: int,
    per_camera: Dict[int, TrackedPerson],
    assigned_in_frame: Optional[Set[int]] = None,
) -> int:
    """Use the ArUco marker ID as the stable cross-camera global ID."""
    if assigned_in_frame is None:
        assigned_in_frame = set()

    global_id = int(aruco_id)
    
    # If the ArUco global ID is already assigned in this frame, we cannot reuse it
    # for another separate matched person. We must allocate a new unique fallback ID.
    if global_id in assigned_in_frame:
        first_cam = list(per_camera.keys())[0]
        first_track = per_camera[first_cam]
        return _get_or_create_global_id(
            matching_state, first_cam, first_track.track_id, assigned_in_frame=assigned_in_frame
        )

    aruco_matches = matching_state.setdefault("aruco_matches", {})
    aruco_matches[aruco_id] = global_id
    
    previous_matches = matching_state.setdefault("previous_matches", {})
    last_seen = matching_state.setdefault("last_seen", {})
    import time
    now = time.time()
    
    for cam_id, track in per_camera.items():
        previous_matches[(cam_id, track.track_id)] = global_id
        last_seen[(cam_id, track.track_id)] = now

    assigned_in_frame.add(global_id)
    return global_id

