"""
RigVision-3D — Person Detection Utilities
==========================================

Pure utility functions for person detection using YOLOv8.

WHAT THIS MODULE DOES:
──────────────────────
1. Detects persons (class 0 only) in video frames using YOLO.
2. Classifies posture using RTMPose keypoints or heuristics.
3. Detects ArUco markers inside each person's bounding box for identity.
4. Returns Detection records with identity metadata.

CALLER OWNS:
────────────
- YOLO model instance
- RTMPose pose model
- ArUco detector
- All state management

This module contains only stateless utility functions.
"""

from __future__ import annotations

import os
os.environ["OPENCV_LOG_LEVEL"] = "OFF"  # Suppress internal OpenCV logging and warnings
from types import SimpleNamespace
from typing import List, Optional, Tuple

import numpy as np


def Detection(
    bbox: Tuple[float, float, float, float],
    confidence: float,
    class_id: int,
    class_name: str,
    foot_point: Tuple[float, float] = (0.0, 0.0),
    posture: str = "standing",
    keypoints: Optional[np.ndarray] = None,
    aruco_id: Optional[int] = None,
    aruco_confidence: float = 0.0,
    personnel_id: Optional[int] = None,
    personnel_confidence: float = 0.0,
    recognition_method: Optional[str] = None,
) -> SimpleNamespace:
    """A detected person in one camera frame.
    
    Attributes:
        bbox: Bounding box as (x1, y1, x2, y2) in pixels.
              (x1, y1) = top-left corner, (x2, y2) = bottom-right corner.
        confidence: Detection confidence from YOLO (0.0 to 1.0).
        class_id: COCO class ID (0 = person only).
        class_name: Human-readable class name ("person").
        foot_point: Estimated foot position at bottom-center of bbox.
                    Used for 3D triangulation.
        posture: Inferred posture ("standing", "sitting", "lying", "bending").
        keypoints: RTMPose keypoints array for posture estimation.
        aruco_id: Physical ArUco marker ID detected in person crop.
        aruco_confidence: Confidence score for marker detection.
        personnel_id: Personnel/ArUco ID (legacy field for compatibility).
        personnel_confidence: Personnel confidence score.
        recognition_method: Method used for identity ("aruco" or None).
    """
    x1, y1, x2, y2 = bbox
    width = x2 - x1
    height = y2 - y1
    computed_foot_point = ((x1 + x2) / 2, y2)
    return SimpleNamespace(
        bbox=bbox,
        confidence=confidence,
        class_id=class_id,
        class_name=class_name,
        foot_point=computed_foot_point if foot_point == (0.0, 0.0) else foot_point,
        posture=posture,
        keypoints=keypoints,
        aruco_id=aruco_id,
        aruco_confidence=aruco_confidence,
        personnel_id=personnel_id if personnel_id is not None else aruco_id,
        personnel_confidence=personnel_confidence if personnel_confidence else aruco_confidence,
        recognition_method=recognition_method,
        center=((x1 + x2) / 2, (y1 + y2) / 2),
        width=width,
        height=height,
        aspect_ratio=width / height if height > 0 else 0.0,
    )


def detect_and_recognize(
    frame: np.ndarray,
    bbox: Tuple[float, float, float, float],
    keypoints: Optional[np.ndarray] = None,
    aruco_detector: Optional[object] = None,
    aruco_dictionary: Optional[object] = None,
    aruco_parameters: Optional[object] = None,
) -> Tuple[Optional[int], float, Optional[str]]:
    """Identify a detected person by scanning their crop for an ArUco marker.
    
    Caller owns the ArUco detector and dictionary instances.

    Args:
        frame: Full video frame (BGR).
        bbox: Person bounding box (x1, y1, x2, y2) in pixels.
        keypoints: Optional RTMPose keypoints (unused, for signature consistency).
        aruco_detector: ArUco detector instance (cv2.aruco.ArucoDetector or None).
        aruco_dictionary: ArUco dictionary (cv2.aruco.getPredefinedDictionary(...)).
        aruco_parameters: ArUco parameters.

    Returns:
        Tuple: (aruco_id, confidence, method_name). 
               (None, 0.0, None) if no marker detected.
    """
    if aruco_dictionary is None:
        return None, 0.0, None

    import cv2

    h, w = frame.shape[:2]
    bx1, by1, bx2, by2 = bbox
    pad_x = 0.08 * (bx2 - bx1)
    pad_y = 0.08 * (by2 - by1)
    x1 = max(0, int(bx1 - pad_x))
    y1 = max(0, int(by1 - pad_y))
    x2 = max(0, int(bx2 + pad_x))
    y2 = max(0, int(by2 + pad_y))
    x1, y1 = min(w - 1, x1), min(h - 1, y1)
    x2, y2 = min(w, x2), min(h, y2)

    person_crop = frame[y1:y2, x1:x2]
    if person_crop.size == 0:
        return None, 0.0, None

    try:
        gray_crop = cv2.cvtColor(person_crop, cv2.COLOR_BGR2GRAY)
        if aruco_detector is not None:
            corners, ids, rejected = aruco_detector.detectMarkers(gray_crop)
        else:
            corners, ids, rejected = cv2.aruco.detectMarkers(
                gray_crop,
                aruco_dictionary,
                parameters=aruco_parameters,
            )

        if ids is None or len(ids) == 0:
            return None, 0.0, None

        marker_ids = ids.flatten().astype(int)
        marker_areas = []
        for marker_corners in corners:
            pts = marker_corners.reshape(-1, 2)
            marker_areas.append(float(cv2.contourArea(pts.astype(np.float32))))

        best_idx = int(np.argmax(marker_areas)) if marker_areas else 0
        crop_area = float(person_crop.shape[0] * person_crop.shape[1])
        confidence = min(1.0, marker_areas[best_idx] / crop_area) if crop_area > 0 else 0.0
        return int(marker_ids[best_idx]), confidence, "aruco"
    except Exception:
        pass

    return None, 0.0, None


def _extract_detections(
    result: object,
    model: object,
    pose_model: Optional[object] = None,
    has_rtmlib: bool = False,
    frame: Optional[np.ndarray] = None,
    aruco_detector: Optional[object] = None,
    aruco_dictionary: Optional[object] = None,
    aruco_parameters: Optional[object] = None,
) -> List[Detection]:
    """Extract YOLO person detections, then enrich with posture and ArUco ID.
    
    Caller owns all model instances.
    
    Args:
        result: YOLO detection result object.
        model: YOLO model instance.
        pose_model: RTMPose model for keypoint extraction (optional).
        has_rtmlib: Whether RTMPose is available.
        frame: Original video frame for ArUco detection (optional).
        aruco_detector: ArUco detector instance.
        aruco_dictionary: ArUco dictionary.
        aruco_parameters: ArUco parameters.
    """
    detections: List[Detection] = []
    if result.boxes is None:
        return detections

    person_cls = 0  # COCO class 0 = person

    for box in result.boxes:
        cls_id = int(box.cls[0].cpu().numpy())
        if cls_id != person_cls:
            continue
        
        bbox = tuple(box.xyxy[0].cpu().numpy().astype(float))
        conf = float(box.conf[0].cpu().numpy())
        cls_name = model.names.get(cls_id, "person")

        det = Detection(
            bbox=bbox,
            confidence=conf,
            class_id=cls_id,
            class_name=cls_name,
        )
        detections.append(det)

    if detections and frame is not None:
        # Enrich detections with posture and ArUco identity
        if has_rtmlib and pose_model is not None:
            bboxes = np.array([det.bbox for det in detections])
            try:
                keypoints_all, scores_all = pose_model.pose_model(frame, bboxes=bboxes)
                for i, det in enumerate(detections):
                    det.keypoints = keypoints_all[i]
                    det.posture = classify_posture(det.bbox, det.keypoints)
            except Exception:
                for det in detections:
                    det.keypoints = None
                    det.posture = classify_posture(det.bbox, None)
        else:
            for det in detections:
                det.keypoints = None
                det.posture = classify_posture(det.bbox, None)

        # Detect ArUco markers inside each person crop
        for det in detections:
            aruco_id, aruco_conf, method = detect_and_recognize(
                frame, det.bbox, det.keypoints, 
                aruco_detector, aruco_dictionary, aruco_parameters
            )
            det.aruco_id = aruco_id
            det.aruco_confidence = aruco_conf
            det.personnel_id = aruco_id
            det.personnel_confidence = aruco_conf
            det.recognition_method = method

    return detections


def classify_posture(bbox: Tuple[float, float, float, float], keypoints: Optional[np.ndarray]) -> str:
    """Classify posture based on person bounding box and RTMPose keypoints."""
    x1, y1, x2, y2 = bbox
    w = x2 - x1
    h = y2 - y1

    if h > 0 and w / h > 1.25:
        return "lying"

    if keypoints is None or len(keypoints) == 0 or keypoints.shape[0] < 17:
        if h > 0 and w / h > 0.8:
            return "sitting"
        return "standing"

    try:
        kpts = keypoints[0] if len(keypoints.shape) == 3 else keypoints

        l_shoulder = kpts[5]
        r_shoulder = kpts[6]
        l_hip = kpts[11]
        r_hip = kpts[12]
        l_ankle = kpts[15]
        r_ankle = kpts[16]

        mid_shoulder_y = (l_shoulder[1] + r_shoulder[1]) / 2
        mid_shoulder_x = (l_shoulder[0] + r_shoulder[0]) / 2
        mid_hip_y = (l_hip[1] + r_hip[1]) / 2
        mid_hip_x = (l_hip[0] + r_hip[0]) / 2
        mid_ankle_y = (l_ankle[1] + r_ankle[1]) / 2

        torso_h = abs(mid_hip_y - mid_shoulder_y)
        torso_w = abs(mid_hip_x - mid_shoulder_x)
        leg_h = abs(mid_ankle_y - mid_hip_y)

        if torso_h > 0 and torso_w / torso_h > 1.0:
            return "bending"

        coords_y = [mid_shoulder_y, mid_hip_y, mid_ankle_y]
        if max(coords_y) - min(coords_y) < 0.25 * w:
            return "lying"

        if torso_h > 0 and leg_h < 0.85 * torso_h:
            return "sitting"

    except Exception:
        pass

    return "standing"


def detect(
    frame: np.ndarray,
    model: object,
    confidence: float = 0.5,
    pose_model: Optional[object] = None,
    has_rtmlib: bool = False,
    aruco_detector: Optional[object] = None,
    aruco_dictionary: Optional[object] = None,
    aruco_parameters: Optional[object] = None,
) -> List[Detection]:
    """Detect persons in one frame and return enriched detections.
    
    Caller owns all model instances.
    
    Args:
        frame: Video frame (BGR).
        model: YOLO model instance.
        confidence: Confidence threshold (0-1).
        pose_model: RTMPose model for posture (optional).
        has_rtmlib: Whether RTMPose is available.
        aruco_detector: ArUco detector instance.
        aruco_dictionary: ArUco dictionary.
        aruco_parameters: ArUco parameters.
    """
    results = model(
        frame,
        conf=confidence,
        classes=[0],  # Person class only
        verbose=False,
    )

    if not results or len(results) == 0:
        return []

    return _extract_detections(
        results[0],
        model,
        pose_model,
        has_rtmlib,
        frame,
        aruco_detector,
        aruco_dictionary,
        aruco_parameters,
    )


def detect_batch(
    frames: List[np.ndarray],
    model: object,
    confidence: float = 0.5,
    pose_model: Optional[object] = None,
    has_rtmlib: bool = False,
    aruco_detector: Optional[object] = None,
    aruco_dictionary: Optional[object] = None,
    aruco_parameters: Optional[object] = None,
) -> List[List[Detection]]:
    """Detect persons in multiple frames and return enriched detections.
    
    Caller owns all model instances.
    
    Args:
        frames: List of video frames (BGR).
        model: YOLO model instance.
        confidence: Confidence threshold (0-1).
        pose_model: RTMPose model for posture (optional).
        has_rtmlib: Whether RTMPose is available.
        aruco_detector: ArUco detector instance.
        aruco_dictionary: ArUco dictionary.
        aruco_parameters: ArUco parameters.
    """
    results = model(
        frames,
        conf=confidence,
        classes=[0],  # Person class only
        verbose=False,
    )

    return [
        _extract_detections(
            result,
            model,
            pose_model,
            has_rtmlib,
            frames[i] if i < len(frames) else None,
            aruco_detector,
            aruco_dictionary,
            aruco_parameters,
        )
        for i, result in enumerate(results)
    ]
