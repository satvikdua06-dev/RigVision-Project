"""
RigVision-3D — Person & PPE Detector
=====================================

Uses YOLOv8 to detect persons and PPE items (hard hats, vests, goggles)
in a single forward pass.

HOW YOLO WORKS (simplified):
─────────────────────────────
YOLO = "You Only Look Once". Traditional detectors scan an image multiple
times at different scales. YOLO processes the entire image in ONE pass:

1. Divide image into a grid (e.g., 80×80 cells)
2. Each cell predicts N bounding boxes + class probabilities
3. Non-Maximum Suppression (NMS) removes overlapping duplicates
4. Output: list of (bounding_box, class, confidence)

This makes YOLO extremely fast — perfect for real-time video at 30fps.

CLASSES:
────────
Default YOLOv8 (COCO dataset):
  - Class 0 = "person"
  - We filter for persons only in the base detector

PPE Detection (future, fine-tuned model):
  - Class 0 = "person"
  - Class 1 = "hardhat"
  - Class 2 = "vest"
  - Class 3 = "goggles"
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
from ultralytics import YOLO


@dataclass
class Detection:
    """A single detected object in one camera frame.
    
    Attributes:
        bbox: Bounding box as (x1, y1, x2, y2) in pixels. 
              (x1,y1) = top-left corner, (x2,y2) = bottom-right corner.
        confidence: How sure the model is (0.0 to 1.0). 
                    Higher = more certain this is really a person.
        class_id: COCO class ID (0 = person).
        class_name: Human-readable class name.
        foot_point: Estimated foot position (bottom-center of bbox).
                    This is what we triangulate to get 3D floor position.
        ppe: Detected PPE items. None until PPE model is integrated.
    """
    bbox: Tuple[float, float, float, float]
    confidence: float
    class_id: int
    class_name: str
    foot_point: Tuple[float, float] = field(default=(0.0, 0.0))
    ppe: Optional[dict] = None
    is_real_ppe: bool = False

    def __post_init__(self) -> None:
        """Calculate foot_point from bbox after initialization."""
        x1, y1, x2, y2 = self.bbox
        # Foot = bottom-center of bounding box
        # This approximates where the person's feet touch the floor
        self.foot_point = ((x1 + x2) / 2, y2)

    @property
    def center(self) -> Tuple[float, float]:
        """Center point of the bounding box."""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def aspect_ratio(self) -> float:
        """Width / Height. Used for cross-camera matching."""
        h = self.height
        return self.width / h if h > 0 else 0.0


class PersonDetector:
    """Wraps YOLOv8 for person + PPE detection.
    
    Usage:
        detector = PersonDetector(model_path="yolov8l.pt", confidence=0.5)
        detections = detector.detect(frame)
        for det in detections:
            print(f"Person at {det.bbox} conf={det.confidence:.2f}")
    
    GPU Acceleration:
        With your RTX 4070, YOLO automatically uses CUDA.
        No code changes needed — Ultralytics handles device selection.
    """

    def __init__(
        self,
        model_path: str = "yolov8l.pt",
        confidence: float = 0.5,
        person_only: bool = True,
        device: Optional[str] = None,
    ) -> None:
        """
        Args:
            model_path: Path to YOLO .pt weights file. Will auto-download if not found.
            confidence: Minimum confidence threshold (0-1). Detections below this are discarded.
            person_only: If True, only detect persons (class 0). If False, detect all COCO classes.
            device: Force device ('cuda', 'cpu', '0'). None = auto-detect.
        """
        self.confidence = confidence
        self.person_only = person_only

        # Resolve model path
        # First check in cv/models/ directory, then current directory
        models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")
        full_path = os.path.join(models_dir, model_path)

        if os.path.exists(full_path):
            load_path = full_path
        elif os.path.exists(model_path):
            load_path = model_path
        else:
            # Ultralytics will auto-download the model
            load_path = model_path
            print(f"[detector] Model not found locally. Ultralytics will download '{model_path}'...")

        self.model = YOLO(load_path)
        if device is None:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.to(device)
        print(f"[detector] Loaded {model_path} on device={self.model.device}")

        # Check if the model has PPE classes (auto-detect by name)
        names = [v.lower() for v in self.model.names.values()]
        self.is_ppe_model = any('hardhat' in n or 'hat' in n for n in names) and any('vest' in n for n in names)

        # Find exact class indices for mapping
        self.cls_mapping = {"person": 0, "hardhat": 1, "vest": 2, "goggles": 3}
        for k, v in self.model.names.items():
            v_lower = v.lower()
            if "person" in v_lower:
                self.cls_mapping["person"] = k
            elif "hardhat" in v_lower or "hat" in v_lower:
                self.cls_mapping["hardhat"] = k
            elif "vest" in v_lower:
                self.cls_mapping["vest"] = k
            elif "goggles" in v_lower or "glass" in v_lower:
                self.cls_mapping["goggles"] = k

    def _associate_ppe_to_persons(
        self,
        persons: List[Detection],
        hardhats: List[Tuple[float, float, float, float]],
        vests: List[Tuple[float, float, float, float]],
        goggles: List[Tuple[float, float, float, float]],
    ) -> None:
        """Associate detected PPE items with persons based on bounding box containment."""
        def compute_containment(person_bbox: Tuple[float, float, float, float], ppe_bbox: Tuple[float, float, float, float]) -> float:
            x1 = max(person_bbox[0], ppe_bbox[0])
            y1 = max(person_bbox[1], ppe_bbox[1])
            x2 = min(person_bbox[2], ppe_bbox[2])
            y2 = min(person_bbox[3], ppe_bbox[3])
            
            inter_area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
            ppe_area = (ppe_bbox[2] - ppe_bbox[0]) * (ppe_bbox[3] - ppe_bbox[1])
            
            return inter_area / ppe_area if ppe_area > 0.0 else 0.0

        for person in persons:
            p_box = person.bbox
            person.ppe = {
                "hardhat": any(compute_containment(p_box, h_box) > 0.7 for h_box in hardhats),
                "vest": any(compute_containment(p_box, v_box) > 0.7 for v_box in vests),
                "goggles": any(compute_containment(p_box, g_box) > 0.7 for g_box in goggles),
            }

    def _extract_detections(self, result) -> List[Detection]:
        """Extract and format detections from a single YOLO inference result."""
        detections: List[Detection] = []
        if result.boxes is None:
            return detections

        person_cls = self.cls_mapping["person"]
        hardhat_cls = self.cls_mapping["hardhat"]
        vest_cls = self.cls_mapping["vest"]
        goggles_cls = self.cls_mapping["goggles"]

        if self.is_ppe_model:
            person_dets: List[Detection] = []
            hardhat_bboxes: List[Tuple[float, float, float, float]] = []
            vest_bboxes: List[Tuple[float, float, float, float]] = []
            goggles_bboxes: List[Tuple[float, float, float, float]] = []

            for box in result.boxes:
                bbox = tuple(box.xyxy[0].cpu().numpy().astype(float))
                conf = float(box.conf[0].cpu().numpy())
                cls_id = int(box.cls[0].cpu().numpy())
                cls_name = self.model.names.get(cls_id, f"class_{cls_id}")

                if cls_id == person_cls:
                    det = Detection(
                        bbox=bbox,
                        confidence=conf,
                        class_id=cls_id,
                        class_name=cls_name,
                        ppe={"hardhat": False, "vest": False, "goggles": False},
                        is_real_ppe=True
                    )
                    person_dets.append(det)
                elif cls_id == hardhat_cls:
                    hardhat_bboxes.append(bbox)
                elif cls_id == vest_cls:
                    vest_bboxes.append(bbox)
                elif cls_id == goggles_cls:
                    goggles_bboxes.append(bbox)

            # Associate PPE to persons
            self._associate_ppe_to_persons(person_dets, hardhat_bboxes, vest_bboxes, goggles_bboxes)
            detections = person_dets
        else:
            # Standard COCO model or person-only
            for box in result.boxes:
                cls_id = int(box.cls[0].cpu().numpy())
                if cls_id != person_cls:
                    continue
                bbox = tuple(box.xyxy[0].cpu().numpy().astype(float))
                conf = float(box.conf[0].cpu().numpy())
                cls_name = self.model.names.get(cls_id, f"class_{cls_id}")

                det = Detection(
                    bbox=bbox,
                    confidence=conf,
                    class_id=cls_id,
                    class_name=cls_name,
                    ppe={"hardhat": True, "vest": True, "goggles": True},
                    is_real_ppe=False
                )
                detections.append(det)

        return detections

    def detect(self, frame: np.ndarray) -> List[Detection]:
        """Run detection on a single frame.
        
        Args:
            frame: BGR image as numpy array (OpenCV format), shape (H, W, 3).
        
        Returns:
            List of Detection objects for persons found in the frame.
        """
        # Determine target classes to run on
        classes_to_run = None
        if self.is_ppe_model:
            classes_to_run = [
                self.cls_mapping["person"],
                self.cls_mapping["hardhat"],
                self.cls_mapping["vest"],
                self.cls_mapping["goggles"]
            ]
        elif self.person_only:
            classes_to_run = [self.cls_mapping["person"]]

        # Run inference
        results = self.model(
            frame,
            conf=self.confidence,
            classes=classes_to_run,
            verbose=False,
        )

        if not results or len(results) == 0:
            return []

        return self._extract_detections(results[0])

    def detect_batch(self, frames: List[np.ndarray]) -> List[List[Detection]]:
        """Run detection on multiple frames simultaneously.
        
        Args:
            frames: List of BGR images.
        
        Returns:
            List of detection lists, one per input frame.
        """
        # Determine target classes to run on
        classes_to_run = None
        if self.is_ppe_model:
            classes_to_run = [
                self.cls_mapping["person"],
                self.cls_mapping["hardhat"],
                self.cls_mapping["vest"],
                self.cls_mapping["goggles"]
            ]
        elif self.person_only:
            classes_to_run = [self.cls_mapping["person"]]

        results = self.model(
            frames,
            conf=self.confidence,
            classes=classes_to_run,
            verbose=False,
        )

        all_detections: List[List[Detection]] = []
        for result in results:
            all_detections.append(self._extract_detections(result))

        return all_detections
