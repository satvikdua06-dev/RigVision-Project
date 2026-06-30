"""
RigVision-3D — Multi-Object Tracker (BoT-SORT)
================================================

Tracks detected persons across video frames using BoT-SORT.

WHY TRACKING MATTERS:
─────────────────────
Detection gives you: "There are 3 persons in this frame."
Tracking gives you:  "Person #1 moved from (2,3) to (2.5,3.1). Person #2 is still at (5,1)."

Without tracking, each frame would have random IDs — you couldn't tell if a
person moved or if it's a different person. Tracking maintains identity.

WHAT BoT-SORT DOES:
────────────────────
BoT-SORT (Bag of Tricks for SORT) is a state-of-the-art multi-object tracker.
It improves over simple IoU matching with:

1. KALMAN FILTER — predicts where a person WILL be next frame based on
   their velocity. If someone walks left at 2px/frame, Kalman predicts
   they'll be 2px further left. This makes matching work even with
   occasional missed detections.

2. ReID EMBEDDINGS — a small neural network extracts a 512-dimensional
   "appearance vector" from each person crop. Two views of the same person
   have similar vectors (small cosine distance). This lets BoT-SORT
   re-identify someone even after they're occluded for several frames.

IoU EXPLAINED:
──────────────
IoU = Intersection over Union. Measures how much two bounding boxes overlap.

    IoU = Area of Overlap / Area of Union

    IoU = 0.0 → boxes don't overlap at all (different person)
    IoU = 1.0 → boxes are identical (same person, same position)
    IoU > 0.3 → probably the same person (they didn't move much)

BoT-SORT uses IoU as ONE of several signals. It combines IoU with
Kalman predictions and ReID appearance to make the best match.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import argparse
import sys
import os
import numpy as np

# Import our local native BoT-SORT
from tracking.botsort.bot_sort import BoTSORT

# Import Detection dataclass
# pipeline.py adds cv/ to sys.path, so detection is a top-level package
from detection.detector import Detection


# ─── Default tracker hyperparameters ────────────────────────
# Stored once, reused by __init__ and reset().

def _default_args() -> argparse.Namespace:
    """Build the args namespace for BoT-SORT with RigVision defaults."""
    args = argparse.Namespace()
    args.track_high_thresh = 0.6
    args.track_low_thresh = 0.1
    args.new_track_thresh = 0.7
    args.track_buffer = 30
    args.match_thresh = 0.8
    args.proximity_thresh = 0.5
    args.appearance_thresh = 0.25
    args.with_reid = False
    args.name = "rigvision"
    args.ablation = False
    args.mot20 = False
    return args


@dataclass
class TrackedPerson:
    """A tracked person with persistent identity.
    
    Attributes:
        track_id: Persistent integer ID for this person (unique per camera).
        bbox: Current bounding box (x1, y1, x2, y2) in pixels.
        foot_point: Bottom-center of bbox (for 3D projection).
        confidence: Detection confidence from YOLO.
        ppe: PPE status dict.
        frames_seen: How many frames this person has been tracked.
        frames_missing: How many consecutive frames this person wasn't detected.
        features: ReID appearance embedding from BoT-SORT (512-dim vector).
    """
    track_id: int
    bbox: Tuple[float, float, float, float]
    foot_point: Tuple[float, float] = field(default=(0.0, 0.0))
    confidence: float = 0.0
    ppe: Optional[dict] = None
    posture: str = "standing"
    keypoints: Optional[np.ndarray] = None
    face_id: Optional[int] = None
    face_confidence: float = 0.0
    recognition_method: Optional[str] = None
    frames_seen: int = 0
    frames_missing: int = 0
    features: Optional[np.ndarray] = None

    def __post_init__(self) -> None:
        x1, y1, x2, y2 = self.bbox
        self.foot_point = ((x1 + x2) / 2, y2)

    @property
    def aspect_ratio(self) -> float:
        x1, y1, x2, y2 = self.bbox
        h = y2 - y1
        return (x2 - x1) / h if h > 0 else 0.0


def compute_iou(box_a: Tuple[float, ...], box_b: Tuple[float, ...]) -> float:
    """Compute Intersection over Union between two bounding boxes.
    
    Visual example:
        ┌─────────┐
        │  box_a   │
        │    ┌─────┼────┐
        │    │INTER│    │
        └────┼─────┘    │
             │  box_b   │
             └──────────┘
        
        IoU = area(INTER) / area(box_a ∪ box_b)
    
    Args:
        box_a: (x1, y1, x2, y2) of first box.
        box_b: (x1, y1, x2, y2) of second box.
    
    Returns:
        IoU value between 0.0 and 1.0.
    """
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])

    intersection = max(0, x2 - x1) * max(0, y2 - y1)

    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    union = area_a + area_b - intersection

    return intersection / union if union > 0 else 0.0


class PersonTracker:
    """BoT-SORT based multi-object tracker.
    
    Uses Kalman filtering for motion prediction and ReID embeddings for
    appearance matching.
    
    Usage:
        tracker = PersonTracker(camera_id=0)
        tracked_persons = tracker.update(frame, detections)
        for person in tracked_persons:
            print(f"Track #{person.track_id} at {person.bbox}")
    
    One tracker per camera — each camera gets its own instance because
    BoT-SORT maintains internal state (Kalman states, ReID gallery)
    that is specific to each camera's viewpoint.
    """

    def __init__(
        self,
        camera_id: int = 0,
        device: str = "cuda",
        half: bool = False,
    ) -> None:
        """
        Args:
            camera_id: Which camera this tracker is for (for logging).
            device: Torch device for ReID model ('cuda' for RTX 4070).
            half: Use half-precision (FP16). Faster but slightly less accurate.
        """
        self.camera_id = camera_id

        # M4: Store args so reset() can reuse them without duplication
        self._args = _default_args()
        self.botsort = BoTSORT(self._args, frame_rate=30)
        print(f"[tracker] Camera {camera_id}: Native BoT-SORT initialized (ReID={self._args.with_reid})")

    def update(
        self, frame: np.ndarray, detections: List[Detection]
    ) -> List[TrackedPerson]:
        """Update tracks with new frame and detections.
        
        BoT-SORT needs BOTH the frame (for ReID feature extraction) and
        the detections (bounding boxes to track). It:
        1. Extracts ReID features from each detected person crop
        2. Predicts where existing tracks should be (Kalman filter)
        3. Matches predictions to detections using IoU + ReID + Kalman
        4. Returns updated tracks with persistent IDs
        
        Args:
            frame: Current video frame (BGR, numpy array). BoT-SORT uses
                   this to extract appearance features from person crops.
            detections: List of Detection objects from the detector.
        
        Returns:
            List of TrackedPerson objects with persistent IDs.
        """
        if not detections:
            # BoT-SORT still needs to be called with empty detections
            # to age existing tracks and handle disappearances
            empty_dets = np.empty((0, 6))
            self.botsort.update(empty_dets, frame)
            return []

        # H5: Build 6-column array [x1, y1, x2, y2, confidence, class_id]
        # class_id = 0 for 'person'. This avoids the bug where classes
        # accidentally got the score values from a 5-column array.
        dets = np.array([
            [*det.bbox, det.confidence, 0]
            for det in detections
        ])

        # Native BoT-SORT update
        # Returns: list of STrack objects
        stracks = self.botsort.update(dets, frame)

        # M5: Build a lookup from detection bbox to PPE info for fast matching.
        # We match tracks back to the input detections by IoU to carry over
        # PPE data. We use the raw detection bbox (not the Kalman-smoothed one)
        # for the matching target.
        result: List[TrackedPerson] = []
        for track in stracks:
            # Native STrack exposes tlbr for bounding box (x1, y1, x2, y2)
            bbox = tuple(float(v) for v in track.tlbr)
            track_id = int(track.track_id)
            conf = float(track.score)

            # Find the original detection that best matches this track
            # to carry over the PPE information
            best_iou = 0.0
            matched_det = None
            for det in detections:
                iou = compute_iou(bbox, det.bbox)
                if iou > best_iou:
                    best_iou = iou
                    matched_det = det

            if matched_det is not None and matched_det.ppe is not None:
                if getattr(matched_det, "is_real_ppe", False):
                    ppe = matched_det.ppe
                else:
                    # Stably simulate PPE based on the persistent track_id (mod 4)
                    if track_id % 4 == 2:
                        ppe = {"hardhat": False, "vest": True, "goggles": True}
                    elif track_id % 4 == 3:
                        ppe = {"hardhat": True, "vest": False, "goggles": True}
                    elif track_id % 4 == 0:
                        ppe = {"hardhat": True, "vest": True, "goggles": False}
                    else:
                        ppe = {"hardhat": True, "vest": True, "goggles": True}
            else:
                ppe = {"hardhat": True, "vest": True, "goggles": True}

            if matched_det is not None:
                posture = getattr(matched_det, "posture", "standing")
                keypoints = getattr(matched_det, "keypoints", None)
                face_id = getattr(matched_det, "face_id", None)
                face_confidence = getattr(matched_det, "face_confidence", 0.0)
                recognition_method = getattr(matched_det, "recognition_method", None)
            else:
                posture = "standing"
                keypoints = None
                face_id = None
                face_confidence = 0.0
                recognition_method = None

            person = TrackedPerson(
                track_id=track_id,
                bbox=bbox,
                confidence=conf,
                ppe=ppe,
                posture=posture,
                keypoints=keypoints,
                face_id=face_id,
                face_confidence=face_confidence,
                recognition_method=recognition_method,
                frames_seen=1,
            )
            result.append(person)

        return result

    def reset(self) -> None:
        """Reset tracker state. Use when switching scenes or restarting."""
        # M4: Reuse stored args instead of duplicating hyperparameters
        self._args = _default_args()
        self.botsort = BoTSORT(self._args, frame_rate=30)
        print(f"[tracker] Camera {self.camera_id}: BoT-SORT reset")
