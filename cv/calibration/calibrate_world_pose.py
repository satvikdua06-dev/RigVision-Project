"""
RigVision-3D — Camera World-Pose Calibration (AprilTag, center-based PnP)
========================================================================

Computes a camera's pose in the ROOM/WORLD frame — its rotation R and translation t
(the world->camera transform) — from a photo of AprilTags placed at known room
positions. See WORLD_POSE_GUIDE.md for the full background.

This version uses each tag's CENTER as one 3D<->2D correspondence (robust, and
immune to the AprilTag corner-ordering pitfall). You need >= 4 tags, spread in 3D
(some on the floor, some on the walls -> not all coplanar). 6 is comfortable.

WHAT YOU PROVIDE
  1. Intrinsics for the camera:   configs/intrinsics_cam_{id}.npz   (K, dist)
  2. A photo from that camera showing the tags:   image.png
  3. A survey JSON mapping each tag id -> its CENTER (x, y, z) in METERS,
     measured from YOUR chosen room origin (X = length, Y = up, Z = width).

SURVEY JSON FORMAT  (configs/world_tags_cam_0.json)
  {
    "tags": {
      "0": [1.00, 0.00, 1.00],     <- floor tag (y = 0)
      "1": [3.80, 0.00, 1.20],     <- floor tag
      "2": [2.40, 0.00, 3.10],     <- floor tag
      "3": [0.80, 0.00, 2.90],     <- floor tag
      "4": [2.00, 1.50, 0.00],     <- WALL tag (y = 1.5, on the z=0 wall)
      "5": [4.50, 1.50, 2.00]      <- WALL tag (on the x=4.5 wall)
    }
  }
  (Keys are the printed AprilTag IDs. Values are [x, y, z] of each tag's CENTRE.)

USAGE
  pip install opencv-contrib-python numpy        # cv2.aruco AprilTag detector
  # (optional, better corners) pip install pupil-apriltags

  python calibrate_world_pose.py --camera_id 0 \
      --image image.png \
      --survey configs/world_tags_cam_0.json

OUTPUT
  configs/world_pose_cam_0.npz   with R, t, P, rvec, tvec, camera_center, error
  Prints the reprojection error and the recovered camera centre so you can sanity
  check it against where the phone is physically mounted.
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Dict, List, Tuple

import cv2
import numpy as np


APRILTAG_FAMILY = "tag36h11"
LOG = "[world-pose]"


# ── Tag detection (pupil-apriltags if available, else cv2.aruco) ────────────────
def detect_tag_centers(gray: np.ndarray) -> Dict[int, Tuple[float, float]]:
    """Return {tag_id: (cx, cy)} pixel centre for every AprilTag found."""
    # Preferred: native AprilTag detector (best corners/centres).
    try:
        from pupil_apriltags import Detector
        det = Detector(families=APRILTAG_FAMILY)
        out = {}
        for d in det.detect(gray):
            out[int(d.tag_id)] = (float(d.center[0]), float(d.center[1]))
        if out:
            print(f"{LOG} detected {len(out)} tags via pupil-apriltags")
        return out
    except ImportError:
        pass

    # Fallback: OpenCV ships AprilTag dictionaries in cv2.aruco.
    aruco = cv2.aruco
    dictionary = aruco.getPredefinedDictionary(aruco.DICT_APRILTAG_36h11)
    try:
        params = aruco.DetectorParameters()
        detector = aruco.ArucoDetector(dictionary, params)
        corners, ids, _ = detector.detectMarkers(gray)
    except AttributeError:  # older OpenCV API
        corners, ids, _ = aruco.detectMarkers(gray, dictionary)

    out = {}
    if ids is not None:
        for c, i in zip(corners, ids.flatten()):
            pts = c.reshape(4, 2)
            out[int(i)] = (float(pts[:, 0].mean()), float(pts[:, 1].mean()))
        print(f"{LOG} detected {len(out)} tags via cv2.aruco")
    return out


def load_intrinsics(configs_dir: str, cam_id: int) -> Tuple[np.ndarray, np.ndarray]:
    path = os.path.join(configs_dir, f"intrinsics_cam_{cam_id}.npz")
    if not os.path.exists(path):
        raise FileNotFoundError(f"missing intrinsics: {path} (run calibrate_intrinsic.py first)")
    with np.load(path) as d:
        K = np.asarray(d["camera_matrix"], dtype=np.float64)
        dist = np.asarray(d["dist_coeffs"], dtype=np.float64).ravel()
    return K, dist


def scale_K_to_image(K: np.ndarray, img_w: int, img_h: int,
                     calib_width: int | None = None) -> np.ndarray:
    """Scale K so it matches the resolution of the photo we're solving against.

    Intrinsics are calibrated at one resolution (often the 1280x720 DroidCam stream);
    if the world-pose photo is a different size, K must be rescaled or solvePnP blows up.
    `calib_width` defaults to the resolution implied by the principal point (2*cx).
    Scaling is uniform (assumes matching aspect ratio, which it should be).
    """
    cx, cy = K[0, 2], K[1, 2]
    calib_w = calib_width or int(round(2 * cx))
    calib_h = int(round(2 * cy))
    if abs(img_w - calib_w) <= 2:
        return K  # already matches
    scale = img_w / calib_w
    if abs((img_w / img_h) - (calib_w / calib_h)) > 0.05:
        print(f"{LOG} WARNING: image aspect {img_w}x{img_h} differs from calibration "
              f"{calib_w}x{calib_h}; uniform scaling may be inaccurate.")
    print(f"{LOG} WARNING: photo is {img_w}x{img_h} but intrinsics ~{calib_w}x{calib_h}. "
          f"Scaling K by {scale:.3f}. For best accuracy, capture the world-pose photo "
          f"through the SAME imaging path the intrinsics were calibrated on (the DroidCam "
          f"stream), not a native full-res camera photo (different FOV/distortion).")
    Ks = K.copy()
    Ks[0, 0] *= scale; Ks[1, 1] *= scale
    Ks[0, 2] *= scale; Ks[1, 2] *= scale
    return Ks


def load_survey(path: str) -> Dict[int, List[float]]:
    with open(path) as f:
        data = json.load(f)
    tags = data.get("tags", data)            # allow either {"tags":{...}} or {...}
    return {int(k): list(map(float, v)) for k, v in tags.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description="Compute a camera's R,t in the room/world frame from AprilTags")
    ap.add_argument("--camera_id", type=int, required=True, help="Camera id (names output file)")
    ap.add_argument("--image", required=True, help="Photo from this camera showing the tags")
    ap.add_argument("--survey", required=True, help="JSON: tag_id -> [x,y,z] centre in metres")
    ap.add_argument("--configs", default="configs", help="Dir with intrinsics + where output goes")
    ap.add_argument("--max_reproj", type=float, default=8.0, help="RANSAC inlier px threshold")
    ap.add_argument("--calib_width", type=int, default=None,
                    help="Resolution width the intrinsics were calibrated at "
                         "(default: inferred from 2*cx). Use if K and photo differ in size.")
    args = ap.parse_args()

    if not os.path.exists(args.image):
        print(f"{LOG} ERROR: image not found: {args.image}")
        return

    K, dist = load_intrinsics(args.configs, args.camera_id)
    survey = load_survey(args.survey)

    img = cv2.imread(args.image)
    if img is None:
        print(f"{LOG} ERROR: could not read image: {args.image}")
        return
    K = scale_K_to_image(K, img.shape[1], img.shape[0], args.calib_width)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    detected = detect_tag_centers(gray)
    if not detected:
        print(f"{LOG} ERROR: no AprilTags detected. Check lighting / family is tag36h11 / tags in view.")
        return

    # Match detected tags to surveyed tags.
    obj_pts, img_pts, used = [], [], []
    for tag_id, world_xyz in survey.items():
        if tag_id in detected:
            obj_pts.append(world_xyz)
            img_pts.append(detected[tag_id])
            used.append(tag_id)

    print(f"{LOG} surveyed tags: {sorted(survey)}")
    print(f"{LOG} detected tags: {sorted(detected)}")
    print(f"{LOG} usable (in both): {sorted(used)}")

    if len(obj_pts) < 4:
        print(f"{LOG} ERROR: only {len(obj_pts)} matched tags; need >= 4. "
              f"Place/measure more tags or check IDs.")
        return

    obj_pts = np.array(obj_pts, dtype=np.float64)
    img_pts = np.array(img_pts, dtype=np.float64)

    # Coplanarity warning: pose is weak if every tag is at the same height.
    if np.ptp(obj_pts[:, 1]) < 0.05:
        print(f"{LOG} WARNING: all tags are coplanar (same Y). Add wall tags at a "
              f"different height for an accurate, unambiguous pose.")

    # Solve. SQPNP is a robust global solver; RANSAC guards against a mis-measured tag.
    ok, rvec, tvec, inliers = cv2.solvePnPRansac(
        obj_pts, img_pts, K, dist,
        reprojectionError=args.max_reproj, flags=cv2.SOLVEPNP_SQPNP)
    if not ok:
        print(f"{LOG} ERROR: solvePnP failed. Check survey coordinates and tag IDs.")
        return

    if inliers is not None and len(inliers) >= 4:
        idx = inliers.ravel()
        rvec, tvec = cv2.solvePnPRefineLM(obj_pts[idx], img_pts[idx], K, dist, rvec, tvec)
    else:
        idx = np.arange(len(obj_pts))

    R, _ = cv2.Rodrigues(rvec)
    t = tvec.reshape(3, 1)
    P = K @ np.hstack([R, t])

    # Reprojection error (lower = better; ~1-2px is good).
    proj, _ = cv2.projectPoints(obj_pts, rvec, tvec, K, dist)
    err = float(np.linalg.norm(img_pts - proj.reshape(-1, 2), axis=1).mean())

    # Camera centre in world: where the phone physically is.
    C = (-R.T @ t).ravel()

    out_path = os.path.join(args.configs, f"world_pose_cam_{args.camera_id}.npz")
    os.makedirs(args.configs, exist_ok=True)
    np.savez_compressed(out_path, R=R, t=t, P=P, rvec=rvec, tvec=tvec,
                        camera_center=C, reprojection_error=err,
                        tags_used=np.array(sorted(used)))

    print("\n" + "=" * 56)
    print(f"{LOG} Camera {args.camera_id} WORLD POSE")
    print("=" * 56)
    print(f"  tags used            : {len(idx)} / {len(obj_pts)} matched")
    print(f"  reprojection error   : {err:.3f} px   {'(good)' if err < 2 else '(HIGH - check survey/IDs)'}")
    print(f"  R (world->camera):\n{np.array2string(R, precision=4, suppress_small=True)}")
    print(f"  t (world->camera): {np.array2string(t.ravel(), precision=4, suppress_small=True)}")
    print(f"  camera centre (x,y,z) in room metres: "
          f"({C[0]:.3f}, {C[1]:.3f}, {C[2]:.3f})")
    print(f"  ^ sanity-check this against where the phone is actually mounted.")
    print(f"\n{LOG} saved -> {out_path}")


if __name__ == "__main__":
    main()
