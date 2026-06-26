"""
RigVision-3D — Extrinsic Camera Calibration
=============================================

Computes the camera's POSITION and ORIENTATION in the room by detecting
ArUco markers placed at known world positions.

USAGE:
    python calibrate_extrinsic.py \
        --camera 0 \
        --intrinsics configs/camera_0.json \
        --markers markers.json \
        --output configs/camera_0.json

PREREQUISITES:
    1. Run calibrate_intrinsic.py first (need K matrix + distortion)
    2. Print ArUco markers (from generate_aruco.py)
    3. Tape markers to walls at known positions
    4. Create markers.json with measured positions:
       {
           "0": {"x": 0.0, "y": 2.0, "z": 0.0},   ← marker ID 0 at (0,2,0) meters
           "1": {"x": 4.0, "y": 2.0, "z": 0.0},   ← marker ID 1 at (4,2,0) meters
           ...
       }

WHAT IS EXTRINSIC CALIBRATION?
──────────────────────────────
Intrinsic = camera's internal properties (lens)
Extrinsic = camera's pose in the world (position + orientation)

We need both to convert pixel coordinates → 3D world coordinates.

The extrinsic parameters are:
  R = 3×3 rotation matrix (which way the camera is pointing)
  t = 3×1 translation vector (where the camera is in the room)

Combined with K (intrinsic), we get the projection matrix:
  P = K @ [R | t]
  
This P is what triangulation.py uses for DLT.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Dict, Tuple

import cv2
import numpy as np


def calibrate_extrinsic(
    camera_source: str,
    intrinsics_path: str,
    markers_path: str,
    output_path: str,
    marker_size_m: float = 0.15,
    dictionary_id: int = cv2.aruco.DICT_6X6_250,
) -> None:
    """Run extrinsic calibration using ArUco markers.
    
    Args:
        camera_source: Camera index or RTSP URL.
        intrinsics_path: Path to intrinsic calibration JSON (from calibrate_intrinsic.py).
        markers_path: Path to JSON with marker world positions.
        output_path: Where to save the complete calibration (updates the intrinsic JSON).
        marker_size_m: Physical size of ArUco markers in meters.
        dictionary_id: ArUco dictionary to use (must match generated markers).
    """
    # Load intrinsic calibration
    with open(intrinsics_path, "r") as f:
        intrinsics = json.load(f)
    
    K = np.array(intrinsics["camera_matrix"], dtype=np.float64)
    dist_coeffs = np.array(intrinsics["dist_coeffs"], dtype=np.float64).flatten()
    
    # Load known marker positions
    with open(markers_path, "r") as f:
        marker_positions = json.load(f)
    
    print(f"📷 Camera: {camera_source}")
    print(f"📐 Known marker positions: {list(marker_positions.keys())}")
    print(f"   Marker size: {marker_size_m}m")
    print()
    print("   Hold camera steady, ensure 4+ markers are visible.")
    print("   Press SPACE to capture, Q to finish.")
    print()
    
    # Open camera
    try:
        cam_index = int(camera_source)
        cap = cv2.VideoCapture(cam_index)
    except ValueError:
        cap = cv2.VideoCapture(camera_source)
    
    if not cap.isOpened():
        print(f"❌ Cannot open camera: {camera_source}")
        return
    
    dictionary = cv2.aruco.getPredefinedDictionary(dictionary_id)
    detector_params = cv2.aruco.DetectorParameters()
    detector = cv2.aruco.ArucoDetector(dictionary, detector_params)
    
    all_obj_points = []
    all_img_points = []
    
    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Detect ArUco markers
        corners, ids, rejected = detector.detectMarkers(gray)
        
        display = frame.copy()
        if ids is not None and len(ids) > 0:
            cv2.aruco.drawDetectedMarkers(display, corners, ids)
            
            # Count how many detected markers have known positions
            known_count = sum(1 for mid in ids.flatten() if str(mid) in marker_positions)
            status = f"Detected {len(ids)} markers ({known_count} with known positions). SPACE to capture."
            cv2.putText(display, status, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        else:
            cv2.putText(display, "No markers detected...", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        
        cv2.imshow("Extrinsic Calibration", display)
        key = cv2.waitKey(1) & 0xFF
        
        if key == ord(' ') and ids is not None:
            # Collect 3D-2D correspondences from detected markers
            obj_pts = []
            img_pts = []
            
            for i, marker_id in enumerate(ids.flatten()):
                str_id = str(marker_id)
                if str_id in marker_positions:
                    pos = marker_positions[str_id]
                    # Use center of marker as the correspondence point
                    center = corners[i][0].mean(axis=0)
                    obj_pts.append([pos["x"], pos["y"], pos["z"]])
                    img_pts.append(center)
            
            if len(obj_pts) >= 4:
                all_obj_points.extend(obj_pts)
                all_img_points.extend(img_pts)
                print(f"  ✅ Captured {len(obj_pts)} marker correspondences (total: {len(all_obj_points)})")
            else:
                print(f"  ⚠️  Only {len(obj_pts)} known markers visible. Need at least 4.")
        
        elif key == ord('q'):
            break
    
    cap.release()
    cv2.destroyAllWindows()
    
    if len(all_obj_points) < 4:
        print(f"❌ Only {len(all_obj_points)} correspondences. Need at least 4.")
        return
    
    # Solve PnP (Perspective-n-Point) to find camera pose
    obj_pts = np.array(all_obj_points, dtype=np.float64)
    img_pts = np.array(all_img_points, dtype=np.float64)
    
    print(f"\n🔧 Running solvePnP with {len(obj_pts)} correspondences...")
    
    success, rvec, tvec = cv2.solvePnP(obj_pts, img_pts, K, dist_coeffs)
    
    if not success:
        print("❌ solvePnP failed!")
        return
    
    # Convert rotation vector to rotation matrix
    R, _ = cv2.Rodrigues(rvec)
    t = tvec
    
    # Camera position in world coordinates
    cam_pos = (-R.T @ t).flatten()
    print(f"  Camera position: ({cam_pos[0]:.2f}, {cam_pos[1]:.2f}, {cam_pos[2]:.2f}) meters")
    
    # Compute projection matrix
    P = K @ np.hstack([R, t])
    
    # Update the calibration JSON with extrinsic data
    intrinsics["rotation_matrix"] = R.tolist()
    intrinsics["translation_vector"] = t.tolist()
    intrinsics["projection_matrix"] = P.tolist()
    intrinsics["camera_position_world"] = cam_pos.tolist()
    intrinsics["rotation_vector"] = rvec.tolist()
    intrinsics["marker_size_m"] = marker_size_m
    intrinsics["num_correspondences"] = len(obj_pts)
    
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    
    with open(output_path, "w") as f:
        json.dump(intrinsics, f, indent=2)
    
    print(f"\n✅ Full calibration (intrinsic + extrinsic) saved to {output_path}")
    print("  This camera is ready for triangulation!")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrinsic camera calibration using ArUco markers")
    parser.add_argument("--camera", required=True, help="Camera index (0,1,2) or RTSP URL")
    parser.add_argument("--intrinsics", required=True, help="Path to intrinsic calibration JSON")
    parser.add_argument("--markers", required=True, help="JSON file with marker world positions")
    parser.add_argument("--output", required=True, help="Output calibration JSON path")
    parser.add_argument("--marker-size", type=float, default=0.15, help="ArUco marker size in meters")
    
    args = parser.parse_args()
    
    calibrate_extrinsic(
        camera_source=args.camera,
        intrinsics_path=args.intrinsics,
        markers_path=args.markers,
        output_path=args.output,
        marker_size_m=args.marker_size,
    )


if __name__ == "__main__":
    main()
