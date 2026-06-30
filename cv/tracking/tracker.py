"""
RigVision-3D — Multi-Object Tracking Utilities
===============================================

Pure utility functions for person tracking using BoT-SORT.

Converts frame-by-frame detections into persistent tracklets (local track IDs per camera).

WHAT THIS MODULE DOES:
──────────────────────
1. Maintains Kalman filters and track states across frames (via BoT-SORT).
2. Matches YOLO detections to existing tracks using IoU and motion prediction.
3. Returns TrackedPerson records with persistent track IDs.

CALLER OWNS:
────────────
- BoT-SORT tracker instance
- All state management
- Frame-to-frame orchestration

This module contains only stateless utility functions that operate on 
supplied BoT-SORT instances.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import List, Optional, Tuple

import numpy as np

# Import Detection record factory for type hints
from detection.detector import Detection




def TrackedPerson(
    track_id: int,
    bbox: Tuple[float, float, float, float],
    foot_point: Tuple[float, float] = (0.0, 0.0),
    confidence: float = 0.0,
    posture: str = "standing",
    keypoints: Optional[np.ndarray] = None,
    aruco_id: Optional[int] = None,
    aruco_confidence: float = 0.0,
    recognition_method: Optional[str] = None,
    frames_seen: int = 0,
    frames_missing: int = 0,
    features: Optional[np.ndarray] = None,
) -> SimpleNamespace:
    """A tracked person with persistent identity.
    
    Attributes:
        track_id: Persistent local track ID (unique per camera).
        bbox: Current bounding box (x1, y1, x2, y2) in pixels.
        foot_point: Bottom-center of bbox (for 3D projection).
        confidence: Detection confidence from YOLO.
        posture: Inferred posture ("standing", "sitting", "lying", "bending").
        keypoints: RTMPose keypoints for this detection.
        aruco_id: Physical ArUco marker ID copied from matched detection.
        aruco_confidence: Marker visibility confidence.
        recognition_method: Method used for identity ("aruco" or None).
        frames_seen: How many frames this track has been matched.
        frames_missing: Consecutive frames where this track had no detection.
        features: ReID appearance embedding (512-dim vector).
        aspect_ratio: Width/height ratio of bounding box.
    """
    x1, y1, x2, y2 = bbox
    h = y2 - y1
    computed_foot_point = ((x1 + x2) / 2, y2)
    return SimpleNamespace(
        track_id=track_id,
        bbox=bbox,
        foot_point=computed_foot_point if foot_point == (0.0, 0.0) else foot_point,
        confidence=confidence,
        posture=posture,
        keypoints=keypoints,
        aruco_id=aruco_id,
        aruco_confidence=aruco_confidence,
        recognition_method=recognition_method,
        frames_seen=frames_seen,
        frames_missing=frames_missing,
        features=features,
        aspect_ratio=(x2 - x1) / h if h > 0 else 0.0,
    )

def compute_iou(box_a: Tuple[float, ...], box_b: Tuple[float, ...]) -> float:
    x1, y1 = max(box_a[0], box_b[0]), max(box_a[1], box_b[1])
    x2, y2 = min(box_a[2], box_b[2]), min(box_a[3], box_b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0

def update_tracker(
    botsort_tracker: object,
    frame: np.ndarray,
    detections: List[Detection],
) -> List[TrackedPerson]:
    """Update local tracks and match detection metadata onto each track.
    
    Caller owns the BoT-SORT tracker instance.
    
    Args:
        botsort_tracker: BoT-SORT tracker instance (from boxmot).
        frame: Current video frame (BGR).
        detections: List of Detection objects from current frame.
    
    Returns:
        List of TrackedPerson objects with persistent track IDs.
    """
    if not detections:
        empty_dets = np.empty((0, 6))
        botsort_tracker.update(empty_dets, frame)
        return []

    # BoT-SORT expects [x1, y1, x2, y2, confidence, class_id].
    dets = np.array([
        [*det.bbox, det.confidence, 0]
        for det in detections
    ])

    stracks = botsort_tracker.update(dets, frame)

    result: List[TrackedPerson] = []
    for track in stracks:
        bbox = tuple(float(v) for v in track.tlbr)
        track_id = int(track.track_id)
        conf = float(track.score)

        # Match each BoT-SORT output back to the original YOLO detection
        # so posture and ArUco identity stay attached.
        best_iou = 0.0
        matched_det = None
        for det in detections:
            iou = compute_iou(bbox, det.bbox)
            if iou > best_iou:
                best_iou = iou
                matched_det = det

        if matched_det is not None:
            posture = getattr(matched_det, "posture", "standing")
            keypoints = getattr(matched_det, "keypoints", None)
            aruco_id = getattr(matched_det, "aruco_id", None)
            aruco_confidence = getattr(matched_det, "aruco_confidence", 0.0)
            recognition_method = getattr(matched_det, "recognition_method", None)
        else:
            posture = "standing"
            keypoints = None
            aruco_id = None
            aruco_confidence = 0.0
            recognition_method = None

        result.append(TrackedPerson(
            track_id=track_id,
            bbox=bbox,
            confidence=conf,
            posture=posture,
            keypoints=keypoints,
            aruco_id=aruco_id,
            aruco_confidence=aruco_confidence,
            recognition_method=recognition_method,
            frames_seen=1,
        ))

    return result

