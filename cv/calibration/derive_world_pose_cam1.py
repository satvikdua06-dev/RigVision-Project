"""
Derives cam 1's world pose from cam 0's world pose + extrinsics (0->1).

    R1 = R_ext @ R0
    t1 = R_ext @ t0 + T_ext

Output: configs/world_pose_cam_1.npz  (same format as world_pose_cam_0.npz)
"""
import numpy as np
import os
import argparse

ap = argparse.ArgumentParser()
ap.add_argument("--configs", default="configs")
ap.add_argument("--master_id", type=int, default=0)
ap.add_argument("--target_id", type=int, default=1)
args = ap.parse_args()

wp = np.load(os.path.join(args.configs, f"world_pose_cam_{args.master_id}.npz"))
ex = np.load(os.path.join(args.configs, f"extrinsics_{args.master_id}_to_{args.target_id}.npz"))

R0 = wp["R"]
t0 = wp["t"].reshape(3, 1)
R_ext = ex["R"]
T_ext = ex["T"].reshape(3, 1)

R1 = R_ext @ R0
t1 = R_ext @ t0 + T_ext
C1 = (-R1.T @ t1).ravel()

K1 = np.load(os.path.join(args.configs, f"intrinsics_cam_{args.target_id}.npz"))["camera_matrix"]
P1 = K1 @ np.hstack([R1, t1])

out = os.path.join(args.configs, f"world_pose_cam_{args.target_id}.npz")
np.savez_compressed(out, R=R1, t=t1, P=P1, camera_center=C1)

print(f"Cam {args.target_id} world pose derived:")
print(f"  camera centre (x,y,z): ({C1[0]:.3f}, {C1[1]:.3f}, {C1[2]:.3f})")
print(f"  saved -> {out}")
