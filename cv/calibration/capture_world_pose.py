"""
RigVision-3D — World-Pose Calibration Frame Capture (AprilTag)
==============================================================

Shows the LIVE DroidCam feed, detects AprilTags (tag36h11) in real time and draws
them, and on SPACE saves the current frame for world-pose calibration.

Why this exists: the world-pose photo MUST come through the same imaging path as the
intrinsics (the DroidCam stream, e.g. 1280x720) — NOT a native full-res phone photo —
or the intrinsics K won't match and solvePnP blows up. This grabs the frame straight
from the stream, so resolution + FOV + distortion all match intrinsics_cam_{id}.npz.

AUTO-SAVE MODE  (--auto_save)
    Pass --survey to tell the script which tag IDs to wait for.  It will keep
    looking until every surveyed tag appears in ONE frame together, then save
    automatically.  Pair with --auto_calibrate to chain straight into PnP.

BLUR HANDLING
    CLAHE + unsharp masking are applied to the grayscale image before detection
    so blurry / low-contrast tags still register.  The raw (undoctored) frame is
    what gets saved.

USAGE
    # manual — press SPACE when all tags are in shot
    python capture_world_pose.py --camera_id 0 --rtsp http://192.168.1.25:4747/video

    # automatic — saves as soon as ALL surveyed tags are seen together
    python capture_world_pose.py --camera_id 0 --rtsp http://192.168.1.25:4747/video \\
        --survey configs/world_tags_cam_0.json --auto_save

    # automatic + run calibration immediately after capture
    python capture_world_pose.py --camera_id 0 --rtsp http://192.168.1.25:4747/video \\
        --survey configs/world_tags_cam_0.json --auto_save --auto_calibrate

CONTROLS
    SPACE  — save the current frame (manual mode; warns if few tags detected)
    Q      — quit

THEN (manual flow)
    python calibrate_world_pose.py --camera_id 0 \\
        --image world_pose_cam_0.png --survey world_tags_cam_0.json --calib_width <stream width>
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from typing import Dict, Optional, Set, Tuple

import cv2
import numpy as np


APRILTAG_FAMILY = "tag36h11"
DETECT_EVERY_N = 2     # detect every N frames to keep the preview smooth

# How many consecutive frames all tags must be seen before auto-saving.
# Avoids saving on a single momentary false-positive.
AUTO_SAVE_CONFIRM_FRAMES = 3


# ── Blur-tolerant preprocessing ─────────────────────────────────────────────────
def enhance_for_detection(gray: np.ndarray) -> np.ndarray:
    """CLAHE + unsharp-mask to improve AprilTag detection on blurry / dim frames."""
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    blurred = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=2)
    sharpened = cv2.addWeighted(enhanced, 1.5, blurred, -0.5, 0)
    return sharpened


# ── Background frame reader ──────────────────────────────────────────────────────
class LatestFrame:
    """Background thread reads frames as fast as the stream delivers; main thread
    always gets the most recent one — no queue build-up, no lag."""

    def __init__(self, src) -> None:
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        self.cap = cv2.VideoCapture(src)
        self.ret, self.frame = False, None
        self.lock = threading.Lock()
        self.running = True
        self.thread = threading.Thread(target=self._update, daemon=True)

    def start(self) -> "LatestFrame":
        self.thread.start()
        return self

    def _update(self) -> None:
        while self.running:
            ret, frame = self.cap.read()
            with self.lock:
                self.ret, self.frame = ret, frame

    def read(self):
        with self.lock:
            return self.ret, self.frame.copy() if self.frame is not None else None

    def release(self) -> None:
        self.running = False
        self.thread.join(timeout=1.0)
        self.cap.release()


# ── AprilTag detection ───────────────────────────────────────────────────────────
class TagDetector:
    """Returns {tag_id: 4x2 corner array} for every AprilTag in a grayscale frame."""

    def __init__(self) -> None:
        self.backend = None
        try:
            from pupil_apriltags import Detector
            self._pupil = Detector(families=APRILTAG_FAMILY)
            self.backend = "pupil-apriltags"
        except ImportError:
            aruco = cv2.aruco
            self._dict = aruco.getPredefinedDictionary(aruco.DICT_APRILTAG_36h11)
            try:
                self._det = aruco.ArucoDetector(self._dict, aruco.DetectorParameters())
                self._new_api = True
            except AttributeError:
                self._new_api = False
            self.backend = "cv2.aruco"

    def detect(self, gray: np.ndarray) -> Dict[int, np.ndarray]:
        out: Dict[int, np.ndarray] = {}
        if self.backend == "pupil-apriltags":
            for d in self._pupil.detect(gray):
                out[int(d.tag_id)] = np.asarray(d.corners, dtype=np.float32)
        else:
            if self._new_api:
                corners, ids, _ = self._det.detectMarkers(gray)
            else:
                corners, ids, _ = cv2.aruco.detectMarkers(gray, self._dict)
            if ids is not None:
                for c, i in zip(corners, ids.flatten()):
                    out[int(i)] = c.reshape(4, 2).astype(np.float32)
        return out


# ── Overlay drawing ──────────────────────────────────────────────────────────────
def draw_overlay(frame: np.ndarray, tags: Dict[int, np.ndarray], saved: int,
                 stream_wh: Tuple[int, int],
                 required_ids: Optional[Set[int]] = None,
                 confirm_count: int = 0) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]

    for tag_id, corners in tags.items():
        pts = corners.astype(int)
        cv2.polylines(out, [pts], isClosed=True, color=(0, 220, 80), thickness=3)
        cx, cy = corners.mean(axis=0).astype(int)
        cv2.circle(out, (cx, cy), 5, (0, 220, 80), -1)
        cv2.putText(out, f"ID {tag_id}", (cx + 8, cy - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 220, 80), 2)

    n = len(tags)
    ids_str = ",".join(str(i) for i in sorted(tags)) if tags else "-"

    if required_ids:
        missing = required_ids - set(tags.keys())
        if missing:
            status = f"{n}/{len(required_ids)} tags  missing:[{','.join(str(i) for i in sorted(missing))}]"
            color = (0, 160, 255)
        else:
            bar = "#" * confirm_count + "." * (AUTO_SAVE_CONFIRM_FRAMES - confirm_count)
            status = f"ALL {len(required_ids)} tags found! [{bar}] saving..."
            color = (0, 255, 200)
    else:
        status = f"{n} tags: [{ids_str}]   ({saved} saved)"
        color = (0, 220, 80) if n else (0, 160, 255)

    cv2.putText(out, status, (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
    cv2.putText(out, "SPACE=save   Q=quit", (12, 70),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (210, 210, 210), 2)
    cv2.putText(out, f"cam stream {stream_wh[0]}x{stream_wh[1]}  (must match intrinsics)",
                (12, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1)
    return out


# ── Survey loading ───────────────────────────────────────────────────────────────
def load_survey_ids(path: str) -> Set[int]:
    with open(path) as f:
        data = json.load(f)
    tags = data.get("tags", data)
    return {int(k) for k in tags}


# ── Main ─────────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Capture a world-pose frame from DroidCam with live AprilTag detection")
    ap.add_argument("--camera_id", type=int, required=True,
                    help="Camera id (names the output file)")
    ap.add_argument("--rtsp", type=str, required=True,
                    help="Stream URL: http://IP:4747/video (DroidCam) / rtsp://... / USB index")
    ap.add_argument("--output_dir", type=str, default=".",
                    help="Where to save the frame")
    ap.add_argument("--survey", type=str, default=None,
                    help="Survey JSON (world_tags_cam_N.json) — required for --auto_save")
    ap.add_argument("--auto_save", action="store_true",
                    help="Automatically save the frame once ALL surveyed tags are detected together")
    ap.add_argument("--auto_calibrate", action="store_true",
                    help="Run calibrate_world_pose.py immediately after auto-saving "
                         "(requires --survey and --auto_save)")
    ap.add_argument("--configs", type=str, default="configs",
                    help="Config dir passed to calibrate_world_pose.py (default: configs)")
    args = ap.parse_args()

    if args.auto_save and not args.survey:
        ap.error("--auto_save requires --survey so the script knows which tag IDs to wait for.")
    if args.auto_calibrate and not args.auto_save:
        ap.error("--auto_calibrate requires --auto_save.")

    required_ids: Optional[Set[int]] = None
    if args.survey:
        if not os.path.exists(args.survey):
            print(f"[ERROR] Survey file not found: {args.survey}")
            return
        required_ids = load_survey_ids(args.survey)
        print(f"[OK] Survey loaded: waiting for tag IDs {sorted(required_ids)}")

    try:
        src = int(args.rtsp)
    except ValueError:
        src = args.rtsp

    reader = LatestFrame(src).start()

    for _ in range(50):
        ret, frame = reader.read()
        if ret and frame is not None:
            break
        time.sleep(0.1)
    else:
        print(f"[ERROR] Cannot open stream: {args.rtsp}")
        reader.release()
        return

    h, w = frame.shape[:2]
    stream_wh = (w, h)
    print(f"[OK] Stream open at {w}x{h}")
    print(f"     calibrate_world_pose.py needs: --calib_width {w}")
    if not args.auto_save:
        print(f"     SPACE=save   Q=quit\n")

    detector = TagDetector()
    print(f"[OK] AprilTag detector backend: {detector.backend}  (family {APRILTAG_FAMILY})")
    print(f"[OK] Blur preprocessing: CLAHE + unsharp mask enabled\n")

    os.makedirs(args.output_dir, exist_ok=True)
    out_path = os.path.join(args.output_dir, f"world_pose_cam_{args.camera_id}.png")

    saved = 0
    tick = 0
    tags: Dict[int, np.ndarray] = {}
    confirm_streak = 0   # consecutive frames where all required tags were seen

    win = f"World-Pose Capture — cam{args.camera_id}"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    while True:
        ret, frame = reader.read()
        if not ret or frame is None:
            time.sleep(0.01)
            continue

        tick += 1
        if tick % DETECT_EVERY_N == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            enhanced = enhance_for_detection(gray)
            tags = detector.detect(enhanced)

        # ── Auto-save logic ────────────────────────────────────────────────────
        if args.auto_save and required_ids:
            all_seen = required_ids.issubset(set(tags.keys()))
            if all_seen:
                confirm_streak += 1
            else:
                confirm_streak = 0

            if confirm_streak >= AUTO_SAVE_CONFIRM_FRAMES:
                cv2.imwrite(out_path, frame)   # save the clean frame (no overlay)
                saved += 1
                print(f"\n[AUTO-SAVE] All {len(required_ids)} tags confirmed across "
                      f"{AUTO_SAVE_CONFIRM_FRAMES} frames.")
                print(f"  Saved -> {out_path}")
                # Show a brief flash on the preview.
                flash = frame.copy()
                cv2.putText(flash, "SAVED!", (w // 2 - 80, h // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 2.5, (0, 255, 0), 5)
                cv2.imshow(win, flash)
                cv2.waitKey(800)
                break

        display = draw_overlay(frame, tags, saved, stream_wh, required_ids, confirm_streak)
        cv2.imshow(win, display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord(' ') and not args.auto_save:
            cv2.imwrite(out_path, frame)
            saved += 1
            n = len(tags)
            note = "" if n >= 4 else "  [warn] <4 tags detected — reposition/light the tags"
            print(f"  Saved: {out_path}  ({n} tags: {sorted(tags)}){note}")

    reader.release()
    cv2.destroyAllWindows()

    if not saved:
        print("\nNo frame saved.")
        return

    print(f"\nDone. Frame saved -> {out_path}")
    calibrate_cmd = (
        f"python calibrate_world_pose.py --camera_id {args.camera_id} "
        f"--image {out_path} --survey {args.survey or 'world_tags_cam_' + str(args.camera_id) + '.json'} "
        f"--configs {args.configs} --calib_width {w}"
    )
    print(f"Next: {calibrate_cmd}")

    if args.auto_calibrate:
        print(f"\n[AUTO-CALIBRATE] Running calibrate_world_pose.py ...")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        calibrate_script = os.path.join(script_dir, "calibrate_world_pose.py")
        result = subprocess.run(
            [sys.executable, calibrate_script,
             "--camera_id", str(args.camera_id),
             "--image", out_path,
             "--survey", args.survey,
             "--configs", args.configs,
             "--calib_width", str(w)],
            check=False,
        )
        if result.returncode != 0:
            print("[ERROR] calibrate_world_pose.py exited with errors. Check output above.")


if __name__ == "__main__":
    main()
