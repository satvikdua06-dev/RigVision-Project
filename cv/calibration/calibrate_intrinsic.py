"""
RigVision-3D — Intrinsic Camera Calibration

Estimates each camera's intrinsic matrix K and lens distortion from 20-30 chessboard
photos placed in `data/cam_{id}/`. Output is `configs/intrinsics_cam_{id}.npz`,
consumed by the CV pipeline's per-zone stereo calibration loader.

USAGE
    python calibrate_intrinsic.py --camera_id 0
"""
from __future__ import annotations

import argparse
import glob
import os

import cv2
import numpy as np


CHESSBOARD_DIM = (10, 7)  # inner corners (cols, rows)
SQUARE_SIZE_M = 0.035     # measured side length of one square


def calibrate_intrinsic(camera_id: int, input_dir: str, output_dir: str) -> None:
    objp = np.zeros((CHESSBOARD_DIM[0] * CHESSBOARD_DIM[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:CHESSBOARD_DIM[0], 0:CHESSBOARD_DIM[1]].T.reshape(-1, 2)
    objp = objp * SQUARE_SIZE_M

    cam_dir = os.path.join(input_dir, f'cam_{camera_id}')
    images = (glob.glob(os.path.join(cam_dir, '*.jpg')) +
              glob.glob(os.path.join(cam_dir, '*.jpeg')) +
              glob.glob(os.path.join(cam_dir, '*.png')))
    if not images:
        print(f"Error: No images found in {cam_dir}")
        return

    print(f"Found {len(images)} images for camera {camera_id}.")

    objpoints: list[np.ndarray] = []
    imgpoints: list[np.ndarray] = []
    frame_size: tuple[int, int] | None = None

    cb_flags = (cv2.CALIB_CB_ADAPTIVE_THRESH |
                cv2.CALIB_CB_NORMALIZE_IMAGE |
                cv2.CALIB_CB_FILTER_QUADS)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

    for fname in images:
        img = cv2.imread(fname)
        if img is None:
            continue
        h, w = img.shape[:2]
        if frame_size is None:
            frame_size = (w, h)
            print(f"  Calibrating at native resolution: {w}x{h}")
        elif (w, h) != frame_size:
            print(f"  Skipping {os.path.basename(fname)}: {w}x{h} != {frame_size[0]}x{frame_size[1]}")
            continue

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, CHESSBOARD_DIM, cb_flags)
        if not ret:
            continue
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        objpoints.append(objp)
        imgpoints.append(corners)

    if not objpoints:
        print("Error: No chessboard detections.")
        return

    # k3 (high-order radial) is unstable for phone/wide lenses and tends to fit noise.
    # k1, k2, p1, p2 capture the real distortion; fixing k3=0 keeps the model stable.
    ret, mtx, dist, _, _ = cv2.calibrateCamera(
        objpoints, imgpoints, frame_size, None, None, flags=cv2.CALIB_FIX_K3)

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f'intrinsics_cam_{camera_id}.npz')
    np.savez_compressed(output_path, camera_matrix=mtx, dist_coeffs=dist, reprojection_error=ret)

    print(f"\nCamera {camera_id}: reprojection error = {ret:.4f} px  ({len(objpoints)} images)")
    print(f"Saved -> {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="RigVision-3D: Intrinsic Camera Calibration")
    parser.add_argument("--camera_id", type=int, required=True)
    parser.add_argument("--input_dir", type=str, default="data")
    parser.add_argument("--output_dir", type=str, default="configs")
    args = parser.parse_args()
    calibrate_intrinsic(args.camera_id, args.input_dir, args.output_dir)


if __name__ == "__main__":
    main()
