from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import argparse
import numpy as np
from tracking.botsort.bot_sort import BoTSORT
from detection.detector import Detection

def _default_args() -> argparse.Namespace:
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
    x1, y1 = max(box_a[0], box_b[0]), max(box_a[1], box_b[1])
    x2, y2 = min(box_a[2], box_b[2]), min(box_a[3], box_b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0

class PersonTracker:
    def __init__(self, camera_id: int = 0, device: str = "cuda", half: bool = False) -> None:
        self.camera_id = camera_id
        self._args = _default_args()
        self.botsort = BoTSORT(self._args, frame_rate=30)

    def update(self, frame: np.ndarray, detections: List[Detection]) -> List[TrackedPerson]:
        if not detections:
            self.botsort.update(np.empty((0, 6)), frame)
            return []
        dets = np.array([[*d.bbox, d.confidence, 0] for d in detections])
        stracks = self.botsort.update(dets, frame)
        res = []
        for t in stracks:
            bbox = tuple(float(v) for v in t.tlbr)
            best_iou, best_d = 0.0, None
            for d in detections:
                iou = compute_iou(bbox, d.bbox)
                if iou > best_iou: best_iou, best_d = iou, d
            ppe = best_d.ppe if (best_d and best_d.ppe and getattr(best_d, "is_real_ppe", False)) else {"hardhat": None, "vest": None, "goggles": None}
            res.append(TrackedPerson(
                track_id=int(t.track_id), bbox=bbox, confidence=float(t.score), ppe=ppe,
                posture=getattr(best_d, "posture", "standing") if best_d else "standing",
                keypoints=getattr(best_d, "keypoints", None) if best_d else None,
                face_id=getattr(best_d, "face_id", None) if best_d else None,
                face_confidence=getattr(best_d, "face_confidence", 0.0) if best_d else 0.0,
                recognition_method=getattr(best_d, "recognition_method", None) if best_d else None,
                frames_seen=1
            ))
        return res

    def reset(self) -> None:
        self.botsort = BoTSORT(self._args, frame_rate=30)
