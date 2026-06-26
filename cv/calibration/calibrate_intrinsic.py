"""
RigVision-3D — Intrinsic Camera Calibration
=============================================

Computes the camera's internal parameters (focal length, principal point,
distortion) by analyzing photos of a checkerboard pattern.

USAGE:
    python calibrate_intrinsic.py --camera 0 --square_size 25 --output configs/camera_0.json
    python calibrate_intrinsic.py --camera rtsp://192.168.1.101:4747/video --square_size 25 --output configs/camera_0.json

WHAT IT DOES:
    1. Opens camera feed (USB index or RTSP URL)
    2. Shows live preview — hold checkerboard in front of camera
    3. Press SPACE to capture a frame (need ~15 frames from different angles)
    4. Press Q when done
    5. Runs OpenCV calibration → saves K matrix + distortion to JSON

WHY INTRINSIC CALIBRATION?
───────────────────────────
Phone cameras have wide-angle lenses that distort the image (straight lines
become curved, especially near edges). Without correcting this distortion,
our 3D triangulation would be inaccurate.

The intrinsic matrix K and distortion coefficients let us:
- Undistort frames (remove lens distortion)
- Convert pixel coordinates to camera ray directions
"""

from __future__ import annotations

import argparse
import json
import os
from typing import List, Tuple

import cv2
import numpy as np


def calibrate_intrinsic(
    camera_source: str,
    checkerboard_size: Tuple[int, int] = (9, 6),
    square_size_mm: float = 25.0,
    output_path: str = "configs/camera_0.json",
    num_frames: int = 15,
) -> None:
    """Run interactive intrinsic calibration.
    
    Args:
        camera_source: Camera index (e.g., "0") or RTSP URL.
        checkerboard_size: (rows, cols) of inner corners.
        square_size_mm: Physical size of each square in mm.
        output_path: Where to save the calibration JSON.
        num_frames: Minimum number of good frames needed.
    """
    # Open camera
    try:
        cam_index = int(camera_source)
        cap = cv2.VideoCapture(cam_index)
    except ValueError:
        cap = cv2.VideoCapture(camera_source)
    
    if not cap.isOpened():
        print(f"❌ Cannot open camera: {camera_source}")
        return
    
    print(f"📷 Camera opened: {camera_source}")
    print(f"   Checkerboard: {checkerboard_size[0]}×{checkerboard_size[1]}, square={square_size_mm}mm")
    print(f"   Need {num_frames} good captures")
    print()
    print("   Hold checkerboard in view. Controls:")
    print("     SPACE = capture frame")
    print("     Q     = finish and calibrate")
    print()
    
    # Prepare object points (3D points of checkerboard corners in real world)
    # These are the KNOWN positions of corners: (0,0,0), (25,0,0), (50,0,0), ...
    objp = np.zeros((checkerboard_size[0] * checkerboard_size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:checkerboard_size[0], 0:checkerboard_size[1]].T.reshape(-1, 2)
    objp *= square_size_mm  # Scale to real-world mm
    
    obj_points: List[np.ndarray] = []  # 3D points in world
    img_points: List[np.ndarray] = []  # 2D points in image
    image_size: Tuple[int, int] = (0, 0)
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("⚠️  Frame grab failed, retrying...")
            continue
        
        image_size = (frame.shape[1], frame.shape[0])  # (width, height)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Try to find checkerboard corners
        found, corners = cv2.findChessboardCorners(gray, checkerboard_size, None)
        
        # Draw corners on display frame
        display = frame.copy()
        if found:
            # Refine corner positions to sub-pixel accuracy
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
            corners_refined = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            cv2.drawChessboardCorners(display, checkerboard_size, corners_refined, found)
            status = f"FOUND - Press SPACE to capture ({len(obj_points)}/{num_frames})"
            cv2.putText(display, status, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        else:
            status = f"Searching for checkerboard... ({len(obj_points)}/{num_frames})"
            cv2.putText(display, status, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        
        cv2.imshow("Intrinsic Calibration", display)
        key = cv2.waitKey(1) & 0xFF
        
        if key == ord(' ') and found:
            # Capture this frame
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
            corners_refined = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            obj_points.append(objp)
            img_points.append(corners_refined)
            print(f"  ✅ Captured frame {len(obj_points)}/{num_frames}")
        
        elif key == ord('q'):
            break
    
    cap.release()
    cv2.destroyAllWindows()
    
    if len(obj_points) < 5:
        print(f"❌ Only {len(obj_points)} captures. Need at least 5 for calibration.")
        return
    
    # Run OpenCV calibration
    print(f"\n🔧 Calibrating with {len(obj_points)} frames...")
    ret, K, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
        obj_points, img_points, image_size, None, None
    )
    
    print(f"  Reprojection error: {ret:.4f} pixels (good if < 1.0)")
    print(f"  Focal length: fx={K[0,0]:.1f}, fy={K[1,1]:.1f}")
    print(f"  Principal point: cx={K[0,2]:.1f}, cy={K[1,2]:.1f}")
    
    # Save to JSON
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    
    calibration_data = {
        "camera_source": camera_source,
        "image_size": list(image_size),
        "camera_matrix": K.tolist(),
        "dist_coeffs": dist_coeffs.tolist(),
        "reprojection_error": ret,
        "num_calibration_frames": len(obj_points),
        "checkerboard_size": list(checkerboard_size),
        "square_size_mm": square_size_mm,
    }
    
    with open(output_path, "w") as f:
        json.dump(calibration_data, f, indent=2)
    
    print(f"\n✅ Intrinsic calibration saved to {output_path}")
    print("  Next step: run calibrate_extrinsic.py to get camera position in room")


def main() -> None:
    parser = argparse.ArgumentParser(description="Intrinsic camera calibration")
    parser.add_argument("--camera", required=True, help="Camera index (0,1,2) or RTSP URL")
    parser.add_argument("--square-size", type=float, default=25.0, help="Checkerboard square size in mm")
    parser.add_argument("--rows", type=int, default=9, help="Checkerboard inner corner rows")
    parser.add_argument("--cols", type=int, default=6, help="Checkerboard inner corner cols")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--num-frames", type=int, default=15, help="Min frames to capture")
    
    args = parser.parse_args()
    
    calibrate_intrinsic(
        camera_source=args.camera,
        checkerboard_size=(args.rows, args.cols),
        square_size_mm=args.square_size,
        output_path=args.output,
        num_frames=args.num_frames,
    )


if __name__ == "__main__":
    main()
