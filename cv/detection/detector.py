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

    def detect(self, frame: np.ndarray) -> List[Detection]:
        """Run detection on a single frame.
        
        Args:
            frame: BGR image as numpy array (OpenCV format), shape (H, W, 3).
        
        Returns:
            List of Detection objects for persons found in the frame.
        """
        # Run inference
        # verbose=False suppresses per-frame logging
        # classes=[0] filters for persons only (COCO class 0)
        results = self.model(
            frame,
            conf=self.confidence,
            classes=[0] if self.person_only else None,
            verbose=False,
        )

        detections: List[Detection] = []

        # results is a list (one per image in batch). We sent one image.
        if not results or len(results) == 0:
            return detections

        result = results[0]
        
        if result.boxes is None:
            return detections

        # Extract detections from YOLO results
        # boxes.xyxy = bounding boxes in (x1, y1, x2, y2) format
        # boxes.conf = confidence scores
        # boxes.cls  = class IDs
        for box in result.boxes:
            bbox = tuple(box.xyxy[0].cpu().numpy().astype(float))
            conf = float(box.conf[0].cpu().numpy())
            cls_id = int(box.cls[0].cpu().numpy())
            cls_name = self.model.names.get(cls_id, f"class_{cls_id}")

            det = Detection(
                bbox=bbox,
                confidence=conf,
                class_id=cls_id,
                class_name=cls_name,
                # PPE detection is placeholder for now
                # Will be populated when PPE-specific model is integrated
                ppe={"hardhat": False, "vest": False, "goggles": False},
            )
            detections.append(det)

        return detections

    def detect_batch(self, frames: List[np.ndarray]) -> List[List[Detection]]:
        """Run detection on multiple frames simultaneously.
        
        Batching is more efficient on GPU because:
        - One data transfer to GPU instead of N transfers
        - GPU processes all frames in parallel
        - 3 cameras × 30fps = 90 frames/sec, batching helps keep up
        
        Args:
            frames: List of BGR images.
        
        Returns:
            List of detection lists, one per input frame.
        """
        results = self.model(
            frames,
            conf=self.confidence,
            classes=[0] if self.person_only else None,
            verbose=False,
        )

        all_detections: List[List[Detection]] = []

        for result in results:
            frame_detections: List[Detection] = []
            if result.boxes is not None:
                for box in result.boxes:
                    bbox = tuple(box.xyxy[0].cpu().numpy().astype(float))
                    conf = float(box.conf[0].cpu().numpy())
                    cls_id = int(box.cls[0].cpu().numpy())
                    cls_name = self.model.names.get(cls_id, f"class_{cls_id}")

                    det = Detection(
                        bbox=bbox,
                        confidence=conf,
                        class_id=cls_id,
                        class_name=cls_name,
                        ppe={"hardhat": False, "vest": False, "goggles": False},
                    )
                    frame_detections.append(det)
            all_detections.append(frame_detections)

        return all_detections
