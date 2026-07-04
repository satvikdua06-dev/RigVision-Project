"""
Quick per-pair reprojection error checker.
Run after calibrate_extrinsic.py to find which pairs are outliers.

Usage:
    python check_pairs.py --master_id 0 --target_id 1 --zone zone_a
"""
from __future__ import annotations
import argparse, os
import cv2
import numpy as np

CHESSBOARD_DIM = (11, 8)
SQUARE_SIZE_M  = 0.045
CB_FLAGS = (cv2.CALIB_CB_ADAPTIVE_THRESH |
            cv2.CALIB_CB_NORMALIZE_IMAGE |
            cv2.CALIB_CB_FILTER_QUADS)
CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master_id", type=int, required=True)
    parser.add_argument("--target_id", type=int, required=True)
    parser.add_argument("--zone",      type=str, required=True)
    parser.add_argument("--intrinsics_dir", default="configs")
    parser.add_argument("--pairs_dir",      default="data/stereo_pairs")
    args = parser.parse_args()

    with np.load(os.path.join(args.intrinsics_dir, f"intrinsics_cam_{args.master_id}.npz")) as d:
        K0, dist0 = d["camera_matrix"], d["dist_coeffs"]
    with np.load(os.path.join(args.intrinsics_dir, f"intrinsics_cam_{args.target_id}.npz")) as d:
        K1, dist1 = d["camera_matrix"], d["dist_coeffs"]
    with np.load(os.path.join(args.intrinsics_dir, f"extrinsics_{args.master_id}_to_{args.target_id}.npz")) as d:
        R, T = d["R"], d["T"]

    objp = np.zeros((CHESSBOARD_DIM[0] * CHESSBOARD_DIM[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:CHESSBOARD_DIM[0], 0:CHESSBOARD_DIM[1]].T.reshape(-1, 2)
    objp *= SQUARE_SIZE_M

    zone_dir = os.path.join(args.pairs_dir, args.zone)
    pair_dirs = sorted([
        os.path.join(zone_dir, e) for e in os.listdir(zone_dir)
        if os.path.isdir(os.path.join(zone_dir, e))
    ])

    results = []
    for pd in pair_dirs:
        def find(stem):
            for ext in (".jpg", ".jpeg", ".png"):
                p = os.path.join(pd, stem + ext)
                if os.path.exists(p): return p
        im = cv2.imread(find(f"cam_{args.master_id}") or "")
        it = cv2.imread(find(f"cam_{args.target_id}") or "")
        if im is None or it is None:
            continue
        gm = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        gt = cv2.cvtColor(it, cv2.COLOR_BGR2GRAY)
        rm, cm = cv2.findChessboardCorners(gm, CHESSBOARD_DIM, CB_FLAGS)
        rt, ct = cv2.findChessboardCorners(gt, CHESSBOARD_DIM, CB_FLAGS)
        if not (rm and rt):
            results.append((os.path.basename(pd), None))
            continue
        cm = cv2.cornerSubPix(gm, cm, (11,11), (-1,-1), CRITERIA)
        ct = cv2.cornerSubPix(gt, ct, (11,11), (-1,-1), CRITERIA)

        # Compute per-pair stereo reprojection error using the calibrated R, T.
        _, rvec0, tvec0 = cv2.solvePnP(objp, cm, K0, dist0)
        R1 = R @ cv2.Rodrigues(rvec0)[0]
        t1 = R @ tvec0 + T
        rvec1, _ = cv2.Rodrigues(R1)

        proj0, _ = cv2.projectPoints(objp, rvec0, tvec0, K0, dist0)
        proj1, _ = cv2.projectPoints(objp, rvec1, t1,    K1, dist1)
        err0 = np.mean(np.linalg.norm(cm.reshape(-1,2)  - proj0.reshape(-1,2), axis=1))
        err1 = np.mean(np.linalg.norm(ct.reshape(-1,2)  - proj1.reshape(-1,2), axis=1))
        results.append((os.path.basename(pd), (err0 + err1) / 2))

    results.sort(key=lambda x: x[1] if x[1] is not None else 999)
    print(f"\nPer-pair reprojection errors (sorted best → worst):\n")
    for name, err in results:
        if err is None:
            print(f"  {name}  — board not detected")
        else:
            flag = "  ← DELETE" if err > 1.5 else ""
            print(f"  {name}  {err:.4f} px{flag}")

    good = [e for _, e in results if e is not None and e <= 1.5]
    print(f"\n{len(good)}/{len(results)} pairs under 1.5px threshold")
    print("Delete the flagged pair folders, then re-run calibrate_extrinsic.py")


if __name__ == "__main__":
    main()
