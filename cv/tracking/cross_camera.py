"""
RigVision-3D — Cross-Camera Matching
======================================

Matches the same person seen across different cameras.

THE PROBLEM:
────────────
Camera 0 tracks "Person #3" in Room A.
Camera 1 tracks "Person #1" in the Corridor.
Are they the same physical person? If yes, we can triangulate their 3D position.

THE SOLUTION — TWO MATCHING SIGNALS:
─────────────────────────────────────
1. EPIPOLAR GEOMETRY (spatial constraint):
   If two cameras see the same 3D point, the corresponding 2D points must
   satisfy a geometric relationship (the "epipolar constraint").
   Points that violate this can't be the same person.

2. APPEARANCE SIMILARITY (visual constraint):
   How similar do the two detections look? Compare aspect ratios,
   and optionally ReID embeddings (deep features of what the person looks like).

We combine both into a cost matrix and use the Hungarian algorithm
to find the optimal one-to-one matching.

COST = 0.7 × epipolar_distance + 0.3 × appearance_distance
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass
class MatchedPerson:
    """A person matched across multiple cameras.
    
    Attributes:
        global_id: Unique ID across all cameras.
        per_camera: Dict mapping camera_id → TrackedPerson from that camera.
        position_3d: Triangulated 3D position (x, y, z) in meters. None if not yet triangulated.
        zone: Which zone this person is in. None if not yet assigned.
    """
    global_id: int
    per_camera: Dict[int, TrackedPerson]
    position_3d: Optional[Tuple[float, float, float]] = None
    zone: Optional[str] = None


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
    """Compute appearance similarity between two tracked persons.
    
    Currently uses aspect ratio similarity as a basic appearance feature.
    When ReID embeddings are available (via BoT-SORT), uses cosine distance.
    
    Args:
        person_a: TrackedPerson from camera A.
        person_b: TrackedPerson from camera B.
    
    Returns:
        Distance value between 0 and 1. Lower = more similar.
    """
    # If we have ReID features, use cosine distance
    if person_a.features is not None and person_b.features is not None:
        # Cosine distance = 1 - cosine_similarity
        dot = np.dot(person_a.features, person_b.features)
        norm_a = np.linalg.norm(person_a.features)
        norm_b = np.linalg.norm(person_b.features)
        if norm_a > 0 and norm_b > 0:
            cosine_sim = dot / (norm_a * norm_b)
            return float(1.0 - cosine_sim)

    # Fallback: aspect ratio similarity
    # Two views of the same person should have similar aspect ratios
    ar_a = person_a.aspect_ratio
    ar_b = person_b.aspect_ratio
    max_ar = max(ar_a, ar_b)
    if max_ar > 0:
        return abs(ar_a - ar_b) / max_ar
    return 1.0


class CrossCameraMapper:
    """Matches tracked persons across multiple cameras.
    
    Usage:
        mapper = CrossCameraMapper()
        
        # Each frame:
        matched = mapper.match(
            per_camera_tracks={
                0: [TrackedPerson(...), ...],  # from camera 0
                1: [TrackedPerson(...), ...],  # from camera 1
                2: [TrackedPerson(...), ...],  # from camera 2
            },
            fundamental_matrices={
                (0, 1): F_01,  # F matrix between cameras 0 and 1
                (0, 2): F_02,
                (1, 2): F_12,
            }
        )
    """

    def __init__(
        self,
        epipolar_weight: float = 0.7,
        appearance_weight: float = 0.3,
        max_distance: float = 100.0,
    ) -> None:
        """
        Args:
            epipolar_weight: Weight for epipolar distance in cost function.
            appearance_weight: Weight for appearance distance.
            max_distance: Maximum allowed cost for a valid match.
        """
        self.epipolar_weight = epipolar_weight
        self.appearance_weight = appearance_weight
        self.max_distance = max_distance
        self.next_global_id = 1
        self.previous_matches: Dict[Tuple[int, int], int] = {}  # (cam_id, track_id) → global_id

    def match(
        self,
        per_camera_tracks: Dict[int, List[TrackedPerson]],
        fundamental_matrices: Optional[Dict[Tuple[int, int], np.ndarray]] = None,
    ) -> List[MatchedPerson]:
        """Match persons across all cameras.
        
        Strategy:
        1. For each pair of cameras, compute cost matrix
        2. Use Hungarian algorithm for optimal matching
        3. Merge matched pairs into MatchedPerson objects
        4. Create single-camera MatchedPerson for unmatched tracks
        
        Args:
            per_camera_tracks: Dict mapping camera_id → list of TrackedPerson.
            fundamental_matrices: Optional dict mapping (cam_i, cam_j) → 3×3 F matrix.
        
        Returns:
            List of MatchedPerson objects with global IDs.
        """
        if fundamental_matrices is None:
            fundamental_matrices = {}

        camera_ids = sorted(per_camera_tracks.keys())
        
        if len(camera_ids) == 0:
            return []
        
        if len(camera_ids) == 1:
            # Single camera — no cross-camera matching needed
            return self._single_camera_output(camera_ids[0], per_camera_tracks[camera_ids[0]])

        # Match across camera pairs
        all_matched: List[MatchedPerson] = []
        used_tracks: Dict[int, set] = {cid: set() for cid in camera_ids}  # cam_id → set of used track_ids

        for i, cam_a in enumerate(camera_ids):
            for cam_b in camera_ids[i + 1:]:
                tracks_a = per_camera_tracks[cam_a]
                tracks_b = per_camera_tracks[cam_b]

                if not tracks_a or not tracks_b:
                    continue

                F = fundamental_matrices.get((cam_a, cam_b))

                matches = self._match_pair(
                    cam_a, tracks_a,
                    cam_b, tracks_b,
                    F,
                )

                for person_a, person_b in matches:
                    if person_a.track_id in used_tracks[cam_a] or person_b.track_id in used_tracks[cam_b]:
                        continue

                    # Try to reuse previous global ID
                    global_id = self._get_or_create_global_id(cam_a, person_a.track_id, cam_b, person_b.track_id)

                    matched = MatchedPerson(
                        global_id=global_id,
                        per_camera={cam_a: person_a, cam_b: person_b},
                    )
                    all_matched.append(matched)
                    used_tracks[cam_a].add(person_a.track_id)
                    used_tracks[cam_b].add(person_b.track_id)

        # Add unmatched tracks as single-camera MatchedPerson
        for cam_id in camera_ids:
            for track in per_camera_tracks[cam_id]:
                if track.track_id not in used_tracks[cam_id]:
                    global_id = self._get_or_create_global_id(cam_id, track.track_id)
                    matched = MatchedPerson(
                        global_id=global_id,
                        per_camera={cam_id: track},
                    )
                    all_matched.append(matched)

        return all_matched

    def _match_pair(
        self,
        cam_a: int, tracks_a: List[TrackedPerson],
        cam_b: int, tracks_b: List[TrackedPerson],
        F: Optional[np.ndarray],
    ) -> List[Tuple[TrackedPerson, TrackedPerson]]:
        """Match tracks between two cameras using cost matrix + Hungarian.
        
        Returns list of (track_from_a, track_from_b) matched pairs.
        """
        if not SCIPY_AVAILABLE:
            return []  # Can't do optimal matching without scipy

        n_a = len(tracks_a)
        n_b = len(tracks_b)
        cost_matrix = np.full((n_a, n_b), self.max_distance)

        for i, ta in enumerate(tracks_a):
            for j, tb in enumerate(tracks_b):
                epi_dist = compute_epipolar_distance(ta.foot_point, tb.foot_point, F)
                app_dist = compute_appearance_distance(ta, tb)

                cost = (self.epipolar_weight * epi_dist +
                        self.appearance_weight * app_dist)
                cost_matrix[i][j] = cost

        # Hungarian algorithm
        row_idx, col_idx = linear_sum_assignment(cost_matrix)

        matches = []
        for r, c in zip(row_idx, col_idx):
            if cost_matrix[r][c] < self.max_distance:
                matches.append((tracks_a[r], tracks_b[c]))

        return matches

    def _single_camera_output(
        self, cam_id: int, tracks: List[TrackedPerson]
    ) -> List[MatchedPerson]:
        """Convert single-camera tracks to MatchedPerson objects."""
        result = []
        for track in tracks:
            global_id = self._get_or_create_global_id(cam_id, track.track_id)
            result.append(MatchedPerson(
                global_id=global_id,
                per_camera={cam_id: track},
            ))
        return result

    def _get_or_create_global_id(self, cam_id: int, track_id: int, cam_id2: Optional[int] = None, track_id2: Optional[int] = None) -> int:
        """Get existing global ID or create a new one."""
        key = (cam_id, track_id)
        if key in self.previous_matches:
            global_id = self.previous_matches[key]
        elif cam_id2 is not None and (cam_id2, track_id2) in self.previous_matches:
            global_id = self.previous_matches[(cam_id2, track_id2)]
        else:
            global_id = self.next_global_id
            self.next_global_id += 1

        self.previous_matches[(cam_id, track_id)] = global_id
        if cam_id2 is not None and track_id2 is not None:
            self.previous_matches[(cam_id2, track_id2)] = global_id

        return global_id
