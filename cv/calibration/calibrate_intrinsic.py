"""
RigVision-3D — Intrinsic Camera Calibration
=============================================

Calculates lens distortion and camera matrix to handle the physical curvature
of each smartphone camera lens. This script complies with the specification
in CALIBRATION_RULES.md.

USAGE:
    # Calibrate camera 1 using images in 'data/cam_1/'
    python calibrate_intrinsic.py --camera_id 1

INPUT:
    A folder containing 20-30 pre-captured .jpg or .png chessboard images
    taken at the target resolution. The script expects these images to be in
    a sub-folder named 'cam_{id}' inside the specified input directory.
    Example: data/cam_1/image_01.jpg

OUTPUT:
    Saves the camera matrix and distortion coefficients into a compressed
    numpy file named 'intrinsics_cam_{id}.npz'.
"""

from __future__ import annotations

import argparse
import glob
import os

import cv2
import numpy as np


TARGET_RESOLUTION = (1920, 1080)
CHESSBOARD_DIM = (9, 6)  
SQUARE_SIZE_M = 0.025  # 25mm


def calibrate_intrinsic(camera_id: int, input_dir: str, output_dir: str) -> None:
    """
    Calculates lens distortion and camera matrix from a set of chessboard images.
    """

    objp = np.zeros((CHESSBOARD_DIM[0] * CHESSBOARD_DIM[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:CHESSBOARD_DIM[0], 0:CHESSBOARD_DIM[1]].T.reshape(-1, 2)
    objp = objp * SQUARE_SIZE_M

    objpoints: list[np.ndarray] = []  # 3d point in real world space
    imgpoints: list[np.ndarray] = []  # 2d points in image plane.

    image_path_pattern = os.path.join(input_dir, f'cam_{camera_id}', '*.jpg')
    images = glob.glob(image_path_pattern)
    images.extend(glob.glob(os.path.join(input_dir, f'cam_{camera_id}', '*.png')))

    if not images:
        print(f"Error: No images found matching '{image_path_pattern}'")
        return

    print(f"Found {len(images)} images for camera {camera_id}. Processing...")

    frame_size = None

    for fname in images:
        img = cv2.imread(fname)
        if img.shape[1::-1] != TARGET_RESOLUTION:
            print(f"Warning: Image {fname} has resolution {img.shape[1::-1]}, but target is {TARGET_RESOLUTION}. Resizing.")
            img = cv2.resize(img, TARGET_RESOLUTION, interpolation=cv2.INTER_AREA)

        if frame_size is None:
            frame_size = (img.shape[1], img.shape[0])

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, CHESSBOARD_DIM, None)

        if ret:
            objpoints.append(objp)
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
            corners2 = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            imgpoints.append(corners2)
            print(f"  - Chessboard found in {os.path.basename(fname)}")
        else:
            print(f"  - Chessboard not found in {os.path.basename(fname)}")

    if not objpoints:
        print("Error: Could not detect chessboard in any of the images.")
        return

    print("\nCalculating camera intrinsics...")
    ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(objpoints, imgpoints, frame_size, None, None)

    if not ret:
        print("Error: Camera calibration failed.")
        return


    output_path = os.path.join(output_dir, f'intrinsics_cam_{camera_id}.npz')
    os.makedirs(output_dir, exist_ok=True)
    np.savez_compressed(output_path, camera_matrix=mtx, dist_coeffs=dist, reprojection_error=ret)

    print(f"\nCalibration successful for camera {camera_id}.")
    print(f"  - Reprojection Error: {ret:.4f}")
    print(f"  - Camera Matrix:\n{mtx}")
    print(f"  - Distortion Coefficients:\n{dist}")
    print(f"\nIntrinsics saved to: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="RigVision-3D: Intrinsic Camera Calibration")
    parser.add_argument("--camera_id", type=int, required=True, help="ID of the camera to calibrate (e.g., 0, 1).")
    parser.add_argument("--input_dir", type=str, default="data", help="Base directory containing calibration images in 'cam_{id}' subfolders.")
    parser.add_argument("--output_dir", type=str, default="configs", help="Directory to save the output .npz file.")
    args = parser.parse_args()

    calibrate_intrinsic(args.camera_id, args.input_dir, args.output_dir)

if __name__ == "__main__":
    main()
