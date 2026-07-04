"""
RigVision-3D — World-Pose Calibration Frame Capture (AprilTag)
==============================================================

Shows the LIVE DroidCam feed, detects AprilTags (tag36h11) in real time and draws
them, and on SPACE saves the current frame for world-pose calibration.

Why this exists: the world-pose photo MUST come through the same imaging path as the
intrinsics (the DroidCam stream, e.g. 1280x720) — NOT a native full-res phone photo —
or the intrinsics K won't match and solvePnP blows up. This grabs the frame straight
from the stream, so resolution + FOV + distortion all match intrinsics_cam_{id}.npz.

USAGE
    python capture_world_pose.py --camera_id 0 --rtsp http://192.168.1.25:4747/video
    # saved frame -> world_pose_cam_0.png   (feed this to calibrate_world_pose.py --image)

CONTROLS
    SPACE  — save the current frame (allowed any time; warns if few tags detected)
    Q      — quit

THEN
    python calibrate_world_pose.py --camera_id 0 \
        --image world_pose_cam_0.png --survey world_tags_cam_0.json --calib_width <stream width>

AIM FOR
    All your surveyed tags visible and detected at once (overlay shows count + IDs),
    sharp (no motion blur), good lighting, tags flat/unoccluded.
"""
from __future__ import annotations

import argparse
import os
import threading
import time
from typing import Dict, List, Tuple

import cv2
import numpy as np


APRILTAG_FAMILY = "tag36h11"
DETECT_EVERY_N = 2     # detect every N frames to keep the preview smooth


class LatestFrame:
    """Background thread reads frames as fast as the stream delivers them; the main
    thread always gets the most recent one — no queue build-up, no lag."""

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


# ── AprilTag detection (pupil-apriltags if available, else cv2.aruco) ───────────
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


def draw_overlay(frame: np.ndarray, tags: Dict[int, np.ndarray], saved: int,
                 stream_wh: Tuple[int, int]) -> np.ndarray:
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
    color = (0, 220, 80) if n else (0, 160, 255)
    cv2.putText(out, f"{n} tags: [{ids_str}]   ({saved} saved)", (12, 36),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
    cv2.putText(out, "SPACE=save   Q=quit", (12, 70),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (210, 210, 210), 2)
    cv2.putText(out, f"cam stream {stream_wh[0]}x{stream_wh[1]}  (must match intrinsics)",
                (12, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Capture a world-pose frame from DroidCam with live AprilTag detection")
    ap.add_argument("--camera_id", type=int, required=True, help="Camera id (names the output file)")
    ap.add_argument("--rtsp", type=str, required=True,
                    help="Stream URL: http://IP:4747/video (DroidCam) / rtsp://... / USB index")
    ap.add_argument("--output_dir", type=str, default=".", help="Where to save the frame")
    args = ap.parse_args()

    try:
        src = int(args.rtsp)       # allow a plain USB index
    except ValueError:
        src = args.rtsp

    reader = LatestFrame(src).start()

    # Wait up to 5s for the first frame.
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
    print(f"     This is the resolution calibrate_world_pose.py needs: --calib_width {w}")
    print(f"     SPACE=save   Q=quit\n")

    detector = TagDetector()
    print(f"[OK] AprilTag detector backend: {detector.backend}  (family {APRILTAG_FAMILY})")

    os.makedirs(args.output_dir, exist_ok=True)
    out_path = os.path.join(args.output_dir, f"world_pose_cam_{args.camera_id}.png")

    saved = 0
    tick = 0
    tags: Dict[int, np.ndarray] = {}

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
            tags = detector.detect(gray)

        display = draw_overlay(frame, tags, saved, stream_wh)
        cv2.imshow(win, display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord(' '):
            cv2.imwrite(out_path, frame)        # save the CLEAN frame (no overlay)
            saved += 1
            n = len(tags)
            note = "" if n >= 4 else "  [warn] <4 tags detected — reposition/light the tags"
            print(f"  Saved: {out_path}  ({n} tags: {sorted(tags)}){note}")

    reader.release()
    cv2.destroyAllWindows()
    if saved:
        print(f"\nDone. Frame saved -> {out_path}")
        print(f"Next: python calibrate_world_pose.py --camera_id {args.camera_id} "
              f"--image {out_path} --survey world_tags_cam_{args.camera_id}.json "
              f"--calib_width {w}")
    else:
        print("\nNo frame saved.")


if __name__ == "__main__":
    main()
