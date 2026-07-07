"""
RigVision-3D — Intrinsic Calibration Frame Capture
===================================================

Captures frames from a single DroidCam stream for intrinsic calibration.
Frames are saved to data/cam_{id}/ at the EXACT resolution DroidCam streams —
this is the only way to guarantee the calibration matches the live pipeline.

USAGE
    # Live DroidCam stream
    python capture_intrinsic.py --camera_id 0 --rtsp http://192.168.1.25:4747/video

    # From a recorded calibration video (must be recorded at same resolution as DroidCam)
    python capture_intrinsic.py --camera_id 0 --video calib_cam0.mp4

CONTROLS
    SPACE  — save current frame (only if chessboard detected)
    F      — force-save regardless (use sparingly)
    Q      — quit

AIM FOR
    20–30 frames covering different angles, distances, and positions in the frame.
    The chessboard must be fully visible in every saved frame.
"""
from __future__ import annotations

import argparse
import os
import threading
import time

import cv2


CHESSBOARD_DIM = (11, 8)    # inner corners — set to (squares_wide - 1, squares_tall - 1)
CB_FLAGS = (cv2.CALIB_CB_ADAPTIVE_THRESH |
            cv2.CALIB_CB_NORMALIZE_IMAGE |
            cv2.CALIB_CB_FILTER_QUADS)
DETECT_EVERY_N = 3           # run chessboard detection every N frames to keep display smooth


class LatestFrame:
    """Background thread reads frames as fast as the stream delivers them.
    Main thread always gets the most recent one — no queue build-up, no lag."""
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture intrinsic calibration frames from DroidCam")
    parser.add_argument("--camera_id", type=int, required=True, help="Camera ID (0–3)")
    parser.add_argument("--rtsp", type=str, default=None,
                        help="Stream URL: http://IP:4747/video (DroidCam free), rtsp://..., or USB index")
    parser.add_argument("--video", type=str, default=None,
                        help="Path to a recorded calibration video (must match DroidCam resolution)")
    parser.add_argument("--output_dir", type=str, default="data")
    args = parser.parse_args()

    if not args.rtsp and not args.video:
        print("[ERROR] Provide either --rtsp or --video")
        return

    out_dir = os.path.join(args.output_dir, f"cam_{args.camera_id}")
    os.makedirs(out_dir, exist_ok=True)

    if args.video:
        if not os.path.exists(args.video):
            print(f"[ERROR] Video file not found: {args.video}")
            return
        src = args.video
        print(f"[video mode] Reading from: {args.video}")
    else:
        try:
            src = int(args.rtsp)
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
    print(f"[OK] Stream open at {w}x{h}  (calibration will use this resolution)")
    print(f"     Saving to: {out_dir}")
    print(f"     SPACE=save (board detected)  F=force-save  Q=quit\n")

    saved = 0
    tick = 0
    found, corners, last_detected_frame = False, None, None

    while True:
        ret, frame = reader.read()
        if not ret or frame is None:
            time.sleep(0.01)
            continue

        tick += 1
        # Run expensive corner detection only every N frames.
        if tick % DETECT_EVERY_N == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            found, corners = cv2.findChessboardCorners(gray, CHESSBOARD_DIM, CB_FLAGS)
            if found:
                last_detected_frame = frame  # snapshot at detection moment

        display = frame.copy()
        if found and corners is not None:
            cv2.drawChessboardCorners(display, CHESSBOARD_DIM, corners, found)
            cv2.putText(display, f"BOARD DETECTED  ({saved} saved) — SPACE to save",
                        (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 220, 80), 2)
        else:
            cv2.putText(display, f"searching...  ({saved} saved)",
                        (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 160, 255), 2)
        cv2.putText(display, f"cam{args.camera_id}  {w}x{h}", (12, h - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)
        cv2.imshow(f"Intrinsic Capture — cam{args.camera_id}", display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord(' '):
            if found and last_detected_frame is not None:
                path = os.path.join(out_dir, f"frame_{saved + 1:03d}.jpg")
                cv2.imwrite(path, last_detected_frame)
                saved += 1
                found = False   # force reposition before next save
                print(f"  Saved: {path}")
            else:
                print("  [skip] Board not detected — reposition and try again")
        elif key == ord('f'):
            path = os.path.join(out_dir, f"frame_{saved + 1:03d}_forced.jpg")
            cv2.imwrite(path, frame)
            saved += 1
            print(f"  Force-saved: {path}")

    reader.release()
    cv2.destroyAllWindows()
    print(f"\nDone. {saved} frames saved to {out_dir}")
    print(f"Next: python calibrate_intrinsic.py --camera_id {args.camera_id}")


if __name__ == "__main__":
    main()
