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
os.environ["OPENCV_LOG_LEVEL"] = "OFF"  # Suppress internal OpenCV logging and warnings
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
    posture: str = "standing"
    keypoints: Optional[np.ndarray] = None
    face_id: Optional[int] = None
    face_confidence: float = 0.0
    recognition_method: Optional[str] = None

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

        # Initialize RTMPose for posture detection
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        try:
            from rtmlib import Body
            import onnxruntime as ort
            
            # Determine appropriate mode based on CUDA provider availability in onnxruntime
            available_providers = ort.get_available_providers()
            if "CUDAExecutionProvider" in available_providers and self.device == "cuda":
                # CUDA is fully available and we are using GPU
                pose_mode = "balanced"
            else:
                # Fallback to CPU execution: use lightweight to maintain high FPS
                pose_mode = "lightweight"
                print(f"[detector] ONNX Runtime GPU acceleration not available (Available: {available_providers}). Using 'lightweight' pose model for CPU efficiency.")
                
            self.pose_model = Body(mode=pose_mode, backend='onnxruntime', device=self.device)
            self.has_rtmlib = True
            print(f"[detector] Loaded RTMPose ({pose_mode} mode) posture model on device={self.device}")
        except Exception as e:
            self.pose_model = None
            self.has_rtmlib = False
            print(f"[detector] rtmlib (RTMPose) not available: {e}. Using rule-based fallback posture classifier.")

        # Initialize QR Code Detection
        import cv2
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
        except Exception:
            try:
                cv2.utils.logging.setLogLevel(0)
            except Exception:
                pass
        self.qr_detector = cv2.QRCodeDetector()

    def detect_and_recognize(
        self,
        frame: np.ndarray,
        bbox: Tuple[float, float, float, float],
        keypoints: Optional[np.ndarray] = None
    ) -> Tuple[Optional[int], float, Optional[str]]:
        """Identify person using QR Code Detection only.
        
        Returns:
            Tuple: (personnel_id, confidence_score, method_name)
        """
        import cv2
        x1, y1, x2, y2 = [max(0, int(v)) for v in bbox]
        h, w = frame.shape[:2]
        x1, y1 = min(w - 1, x1), min(h - 1, y1)
        x2, y2 = min(w, x2), min(h, y2)
        
        person_crop = frame[y1:y2, x1:x2]
        if person_crop.size == 0:
            return None, 0.0, None
            
        # ─── Step 1: QR Code Detector (High Confidence / Deterministic) ───
        try:
            # Detect and decode QR Code
            retval, points, _ = self.qr_detector.detectAndDecode(person_crop)
            if retval:
                # Strip spaces, check if it maps to person ID
                clean_val = retval.strip().lower()
                personnel_id = None
                if clean_val.isdigit():
                    personnel_id = int(clean_val)
                elif clean_val.startswith("person_"):
                    id_part = clean_val.split("_")[-1]
                    if id_part.isdigit():
                        personnel_id = int(id_part)
                
                if personnel_id is not None:
                    return personnel_id, 1.0, "qr"
        except Exception as e:
            pass
            
        return None, 0.0, None

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

        # Run posture detection on all extracted person detections
        if detections:
            person_dets = detections
            if self.has_rtmlib:
                bboxes = np.array([det.bbox for det in person_dets])
                try:
                    keypoints_all, scores_all = self.pose_model.pose_model(result.orig_img, bboxes=bboxes)
                    for i, det in enumerate(person_dets):
                        kpts = keypoints_all[i]
                        det.keypoints = kpts
                        det.posture = self._classify_posture(det.bbox, kpts)
                except Exception as e:
                    print(f"[detector] Pose estimation error: {e}")
                    for det in person_dets:
                        det.keypoints = None
                        det.posture = self._classify_posture(det.bbox, None)
            else:
                for det in person_dets:
                    det.keypoints = None
                    det.posture = self._classify_posture(det.bbox, None)

            # Run multi-modal face & QR recognition
            for det in person_dets:
                face_id, face_conf, method = self.detect_and_recognize(result.orig_img, det.bbox, det.keypoints)
                det.face_id = face_id
                det.face_confidence = face_conf
                det.recognition_method = method

        return detections

    @staticmethod
    def _classify_posture(bbox: Tuple[float, float, float, float], keypoints: Optional[np.ndarray]) -> str:
        """Classify posture based on person bounding box and RTMPose keypoints.
        
        postures: "standing", "sitting", "bending", "lying", "unknown"
        """
        x1, y1, x2, y2 = bbox
        w = x2 - x1
        h = y2 - y1
        
        # 1. Bounding box check for lying
        if h > 0 and w / h > 1.25:
            return "lying"
            
        if keypoints is None or len(keypoints) == 0 or keypoints.shape[0] < 17:
            # Fallback aspect ratio classifier
            if h > 0:
                if w / h > 0.8:
                    return "sitting"
            return "standing"
            
        try:
            # Ensure keypoints has shape (17, 2)
            kpts = keypoints[0] if len(keypoints.shape) == 3 else keypoints
            
            l_shoulder = kpts[5]
            r_shoulder = kpts[6]
            l_hip = kpts[11]
            r_hip = kpts[12]
            l_knee = kpts[13]
            r_knee = kpts[14]
            l_ankle = kpts[15]
            r_ankle = kpts[16]
            
            # Midpoints
            mid_shoulder_y = (l_shoulder[1] + r_shoulder[1]) / 2
            mid_shoulder_x = (l_shoulder[0] + r_shoulder[0]) / 2
            mid_hip_y = (l_hip[1] + r_hip[1]) / 2
            mid_hip_x = (l_hip[0] + r_hip[0]) / 2
            mid_knee_y = (l_knee[1] + r_knee[1]) / 2
            mid_ankle_y = (l_ankle[1] + r_ankle[1]) / 2
            
            torso_h = abs(mid_hip_y - mid_shoulder_y)
            torso_w = abs(mid_hip_x - mid_shoulder_x)
            leg_h = abs(mid_ankle_y - mid_hip_y)
            
            # 2. Bending Check: torso is horizontal
            if torso_h > 0 and torso_w / torso_h > 1.0:
                return "bending"
                
            # 3. Lying Check by keypoints: head, hip, ankle are horizontally aligned
            coords_y = [mid_shoulder_y, mid_hip_y, mid_ankle_y]
            if max(coords_y) - min(coords_y) < 0.25 * w:  # horizontal spread is much larger than vertical spread
                return "lying"
                
            # 4. Sitting Check:
            # If the legs are bent, the vertical height of the legs (hip to ankle) is small compared to the torso
            if torso_h > 0 and leg_h < 0.85 * torso_h:
                return "sitting"
                
        except Exception:
            pass
            
        return "standing"

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
