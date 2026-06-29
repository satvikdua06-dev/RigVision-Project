"""
RigVision-3D — Extrinsic Camera Calibration
=============================================

Calculates the relative 3D spatial transformation (Rotation and Translation)
between two mounted smartphones. This script complies with the specification
in CALIBRATION_RULES.md.

USAGE:
    # Calculate transform from camera 0 (master) to camera 1 (target)
    python calibrate_extrinsic.py --master_id 0 --target_id 1

PREREQUISITES:
    1. Intrinsic calibration must be completed for both cameras using
       `calibrate_intrinsic.py`.
    2. A single pair of strictly synchronized photos (one from each camera)
       viewing the exact same standard chessboard must be available.

INPUT:
    - `intrinsics_cam_{id}.npz` files for both master and target cameras.
    - A synchronized image pair, e.g., `data/stereo_pairs/cam_0.jpg` and
      `data/stereo_pairs/cam_1.jpg`.

OUTPUT:
    Saves the resulting Rotation Matrix `R` and Translation Vector `T` to
    `extrinsics_{master_id}_to_{target_id}.npz`.
"""

from __future__ import annotations

import argparse
import os

import cv2
import numpy as np

# --- Constants ---
# Hardcoded target resolution to ensure frame consistency.
TARGET_RESOLUTION = (1920, 1080)
# Inner corner dimensions of the standard printed chessboard.
CHESSBOARD_DIM = (9, 6)  # (width, height) of inner corners
# Physical size of one chessboard square in meters.
SQUARE_SIZE_M = 0.025  # 25mm


def calibrate_extrinsic(
    master_id: int, target_id: int, intrinsics_dir: str, input_dir: str, output_dir: str
) -> None:
    """
    Calculates the relative 3D spatial transformation (Rotation and Translation)
    between two cameras (master and target).
    """
    # Load intrinsic parameters for both cameras
    try:
        with np.load(os.path.join(intrinsics_dir, f'intrinsics_cam_{master_id}.npz')) as data:
            K_master = data['camera_matrix']
            dist_master = data['dist_coeffs']
        with np.load(os.path.join(intrinsics_dir, f'intrinsics_cam_{target_id}.npz')) as data:
            K_target = data['camera_matrix']
            dist_target = data['dist_coeffs']
    except FileNotFoundError as e:
        print(f"Error: Could not load intrinsic file. Make sure you have run calibrate_intrinsic.py for both cameras. Details: {e}")
        return

    # Load the synchronized image pair
    img_master_path = os.path.join(input_dir, f'cam_{master_id}.jpg')
    img_target_path = os.path.join(input_dir, f'cam_{target_id}.jpg')

    img_master = cv2.imread(img_master_path)
    img_target = cv2.imread(img_target_path)

    if img_master is None or img_target is None:
        print("Error: Could not load synchronized image pair.")
        print(f"  - Looked for: {img_master_path}")
        print(f"  - Looked for: {img_target_path}")
        return

    print(f"Loaded synchronized images for master ({master_id}) and target ({target_id}).")

    # Resize to target resolution
    if img_master.shape[1::-1] != TARGET_RESOLUTION:
        img_master = cv2.resize(img_master, TARGET_RESOLUTION, interpolation=cv2.INTER_AREA)
    if img_target.shape[1::-1] != TARGET_RESOLUTION:
        img_target = cv2.resize(img_target, TARGET_RESOLUTION, interpolation=cv2.INTER_AREA)

    frame_size = (img_master.shape[1], img_master.shape[0])
    gray_master = cv2.cvtColor(img_master, cv2.COLOR_BGR2GRAY)
    gray_target = cv2.cvtColor(img_target, cv2.COLOR_BGR2GRAY)

    # Prepare object points
    objp = np.zeros((CHESSBOARD_DIM[0] * CHESSBOARD_DIM[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:CHESSBOARD_DIM[0], 0:CHESSBOARD_DIM[1]].T.reshape(-1, 2)
    objp = objp * SQUARE_SIZE_M

    # Find chessboard corners in both views
    ret_master, corners_master = cv2.findChessboardCorners(gray_master, CHESSBOARD_DIM, None)
    ret_target, corners_target = cv2.findChessboardCorners(gray_target, CHESSBOARD_DIM, None)

    if not (ret_master and ret_target):
        print("Error: Chessboard not detected in one or both images. Cannot compute extrinsics.")
        return

    print("Chessboard detected in both images. Refining corners...")

    # Refine corner coordinates to sub-pixel accuracy
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    corners_master_refined = cv2.cornerSubPix(gray_master, corners_master, (11, 11), (-1, -1), criteria)
    corners_target_refined = cv2.cornerSubPix(gray_target, corners_target, (11, 11), (-1, -1), criteria)

    # Use stereoCalibrate to find the transformation between cameras
    print("Computing stereo calibration...")
    flags = cv2.CALIB_FIX_INTRINSIC  # Keep pre-computed intrinsics locked

    # stereoCalibrate needs lists of points
    objpoints = [objp]
    imgpoints_master = [corners_master_refined]
    imgpoints_target = [corners_target_refined]

    ret, _, _, _, _, R, T, E, F = cv2.stereoCalibrate(
        objpoints,
        imgpoints_master,
        imgpoints_target,
        K_master,
        dist_master,
        K_target,
        dist_target,
        frame_size,
        flags=flags,
        criteria=criteria
    )

    if not ret:
        print("Error: Stereo calibration failed.")
        return

    # Save the resulting Rotation Matrix R and Translation Vector T
    output_path = os.path.join(output_dir, f'extrinsics_{master_id}_to_{target_id}.npz')
    os.makedirs(output_dir, exist_ok=True)
    np.savez_compressed(
        output_path,
        R=R,
        T=T,
        reprojection_error=ret
    )

    print("\nExtrinsic calibration successful.")
    print(f"  - Reprojection Error: {ret:.4f}")
    print(f"  - Rotation Matrix (R):\n{R}")
    print(f"  - Translation Vector (T):\n{T}")
    print(f"\nExtrinsics saved to: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="RigVision-3D: Extrinsic Stereo Camera Calibration")
    parser.add_argument("--master_id", type=int, required=True, help="ID of the master camera.")
    parser.add_argument("--target_id", type=int, required=True, help="ID of the target camera.")
    parser.add_argument("--intrinsics_dir", type=str, default="configs", help="Directory containing intrinsic .npz files.")
    parser.add_argument("--input_dir", type=str, default="data/stereo_pairs", help="Directory with synchronized image pairs.")
    parser.add_argument("--output_dir", type=str, default="configs", help="Directory to save the output extrinsic .npz file.")
    args = parser.parse_args()

    if args.master_id == args.target_id:
        print("Error: Master and Target camera IDs cannot be the same.")
        return

    calibrate_extrinsic(args.master_id, args.target_id, args.intrinsics_dir, args.input_dir, args.output_dir)


if __name__ == "__main__":
    main()
