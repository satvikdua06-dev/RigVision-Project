import numpy as np
import argparse

ap = argparse.ArgumentParser()
ap.add_argument("--camera_id", type=int, default=0)
ap.add_argument("--configs", type=str, default="configs")
args = ap.parse_args()

d = np.load(f"{args.configs}/world_pose_cam_{args.camera_id}.npz")
print("Master cam position (x,y,z):", d["camera_center"])
print("Reprojection error:", d["reprojection_error"], "px")
