"""
RigVision-3D — Extrinsic Stereo Camera Calibration

Solves the relative pose (R, T) between a zone's two cameras from synchronized
chessboard image pair(s). Output is `configs/extrinsics_{master}_to_{target}.npz`,
consumed by the CV pipeline's per-zone stereo calibration loader.

INPUT
    data/stereo_pairs/{zone}/cam_{master}.* + cam_{target}.*           (single pair)
    data/stereo_pairs/{zone}/pair_NN/cam_{master}.* + cam_{target}.*   (multi-pair)

USAGE
    python calibrate_extrinsic.py --master_id 0 --target_id 1 --zone zone_a
"""
from __future__ import annotations

import argparse
import os

import cv2
import numpy as np


CHESSBOARD_DIM = (10, 7)
SQUARE_SIZE_M = 0.035


def _find_image(directory: str, stem: str) -> str | None:
    for ext in (".png", ".jpg", ".jpeg"):
        p = os.path.join(directory, stem + ext)
        if os.path.exists(p):
            return p
    return None


def calibrate_extrinsic(master_id: int, target_id: int, intrinsics_dir: str,
                        input_dir: str, output_dir: str) -> None:
    try:
        with np.load(os.path.join(intrinsics_dir, f'intrinsics_cam_{master_id}.npz')) as data:
            K_master, dist_master = data['camera_matrix'], data['dist_coeffs']
        with np.load(os.path.join(intrinsics_dir, f'intrinsics_cam_{target_id}.npz')) as data:
            K_target, dist_target = data['camera_matrix'], data['dist_coeffs']
    except FileNotFoundError as e:
        print(f"Error: missing intrinsics ({e}). Run calibrate_intrinsic.py first.")
        return

    pair_dirs: list[str] = []
    if _find_image(input_dir, f'cam_{master_id}') is not None:
        pair_dirs.append(input_dir)
    elif os.path.isdir(input_dir):
        for entry in sorted(os.listdir(input_dir)):
            sub = os.path.join(input_dir, entry)
            if os.path.isdir(sub) and _find_image(sub, f'cam_{master_id}') is not None:
                pair_dirs.append(sub)

    if not pair_dirs:
        print(f"Error: no stereo pairs in {input_dir}")
        return

    objp = np.zeros((CHESSBOARD_DIM[0] * CHESSBOARD_DIM[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:CHESSBOARD_DIM[0], 0:CHESSBOARD_DIM[1]].T.reshape(-1, 2)
    objp = objp * SQUARE_SIZE_M

    cb_flags = (cv2.CALIB_CB_ADAPTIVE_THRESH |
                cv2.CALIB_CB_NORMALIZE_IMAGE |
                cv2.CALIB_CB_FILTER_QUADS)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

    objpoints: list[np.ndarray] = []
    pts_master: list[np.ndarray] = []
    pts_target: list[np.ndarray] = []
    frame_size: tuple[int, int] | None = None

    for pd in pair_dirs:
        mp = _find_image(pd, f'cam_{master_id}')
        tp = _find_image(pd, f'cam_{target_id}')
        im = cv2.imread(mp) if mp else None
        it = cv2.imread(tp) if tp else None
        if im is None or it is None:
            continue
        if frame_size is None:
            frame_size = (im.shape[1], im.shape[0])
        elif (im.shape[1], im.shape[0]) != frame_size:
            continue
        gm = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        gt = cv2.cvtColor(it, cv2.COLOR_BGR2GRAY)
        rm, cm = cv2.findChessboardCorners(gm, CHESSBOARD_DIM, cb_flags)
        rt, ct = cv2.findChessboardCorners(gt, CHESSBOARD_DIM, cb_flags)
        if not (rm and rt):
            continue
        cm = cv2.cornerSubPix(gm, cm, (11, 11), (-1, -1), criteria)
        ct = cv2.cornerSubPix(gt, ct, (11, 11), (-1, -1), criteria)
        objpoints.append(objp)
        pts_master.append(cm)
        pts_target.append(ct)

    if not objpoints:
        print("Error: no valid pairs.")
        return

    ret, _, _, _, _, R, T, _, F = cv2.stereoCalibrate(
        objpoints, pts_master, pts_target,
        K_master, dist_master, K_target, dist_target,
        frame_size,
        flags=cv2.CALIB_FIX_INTRINSIC,
        criteria=criteria,
    )

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f'extrinsics_{master_id}_to_{target_id}.npz')
    np.savez_compressed(output_path, R=R, T=T, F=F, reprojection_error=ret)

    print(f"\nStereo {master_id}->{target_id}: reprojection error = {ret:.4f} px  ({len(objpoints)} pair(s))")
    print(f"  baseline |T| = {np.linalg.norm(T):.3f} m")
    print(f"Saved -> {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="RigVision-3D: Extrinsic Stereo Camera Calibration")
    parser.add_argument("--master_id", type=int, required=True)
    parser.add_argument("--target_id", type=int, required=True)
    parser.add_argument("--zone", type=str, required=True)
    parser.add_argument("--intrinsics_dir", type=str, default="configs")
    parser.add_argument("--input_dir", type=str, default="data/stereo_pairs")
    parser.add_argument("--output_dir", type=str, default="configs")
    args = parser.parse_args()

    if args.master_id == args.target_id:
        print("Error: master and target IDs must differ.")
        return

    zone_dir = os.path.join(args.input_dir, args.zone)
    calibrate_extrinsic(args.master_id, args.target_id, args.intrinsics_dir, zone_dir, args.output_dir)


if __name__ == "__main__":
    main()
