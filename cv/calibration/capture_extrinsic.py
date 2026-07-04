"""
RigVision-3D — Extrinsic Stereo Calibration Frame Capture
==========================================================

Captures SIMULTANEOUS frame pairs from two DroidCam RTSP streams for extrinsic
(stereo) calibration. Both cameras must already be in their FINAL mounted positions
— do not move them after this step.

The printed checkerboard must be visible to BOTH cameras at the same time. Place
it in the overlapping FOV region and vary position + angle across 15–20 captures.

USAGE
    python capture_extrinsic.py --zone zone_a \
        --master_id 0 --rtsp0 rtsp://192.168.1.5:4747/video \
        --target_id 1 --rtsp1 rtsp://192.168.1.6:4747/video

CONTROLS
    SPACE  — save pair (only if board detected in BOTH cameras)
    F      — force-save pair regardless
    Q      — quit

OUTPUT
    data/stereo_pairs/<zone>/pair_001/cam_0.jpg + cam_1.jpg
    data/stereo_pairs/<zone>/pair_002/cam_0.jpg + cam_1.jpg
    ...

VERIFY AFTER RUNNING calibrate_extrinsic.py
    Check that |T| printed matches your tape-measure baseline (±10%).
    If it's off, the most common cause is the checkerboard was partially
    out of frame in too many pairs — try again with more central placement.
"""
from __future__ import annotations

import argparse
import os
import threading
import time

import cv2
import numpy as np


CHESSBOARD_DIM = (11, 8)
CB_FLAGS = (cv2.CALIB_CB_ADAPTIVE_THRESH |
            cv2.CALIB_CB_NORMALIZE_IMAGE |
            cv2.CALIB_CB_FILTER_QUADS)


class StreamReader:
    """Reads the latest frame from an RTSP stream in a background thread.
    The main thread always gets the freshest frame without blocking on decode."""

    def __init__(self, src: str, name: str) -> None:
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        try:
            src_parsed = int(src)
        except ValueError:
            src_parsed = src
        self.cap = cv2.VideoCapture(src_parsed)
        self.name = name
        self.ret = False
        self.frame = None
        self.lock = threading.Lock()
        self.running = True
        self.thread = threading.Thread(target=self._update, daemon=True)

    def start(self) -> "StreamReader":
        self.thread.start()
        return self

    def _update(self) -> None:
        while self.running:
            ret, frame = self.cap.read()
            with self.lock:
                self.ret = ret
                self.frame = frame

    def read(self):
        with self.lock:
            return self.ret, self.frame.copy() if self.frame is not None else None

    def resolution(self):
        with self.lock:
            if self.frame is not None:
                return self.frame.shape[1], self.frame.shape[0]
        return None

    def release(self) -> None:
        self.running = False
        self.thread.join(timeout=1.0)
        self.cap.release()


def detect_board(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    found, corners = cv2.findChessboardCorners(gray, CHESSBOARD_DIM, CB_FLAGS)
    return found, corners


def annotate(frame, found, corners, label, saved):
    out = frame.copy()
    h, w = out.shape[:2]
    if found:
        cv2.drawChessboardCorners(out, CHESSBOARD_DIM, corners, found)
        cv2.putText(out, f"DETECTED  ({saved} pairs saved)", (12, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 220, 80), 2)
    else:
        cv2.putText(out, f"searching...  ({saved} pairs saved)", (12, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 160, 255), 2)
    cv2.putText(out, label, (12, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture stereo extrinsic calibration pairs")
    parser.add_argument("--zone", type=str, required=True, help="zone_a or zone_b")
    parser.add_argument("--master_id", type=int, required=True, help="Master camera ID")
    parser.add_argument("--target_id", type=int, required=True, help="Target camera ID")
    parser.add_argument("--rtsp0", type=str, required=True, help="RTSP URL for master camera")
    parser.add_argument("--rtsp1", type=str, required=True, help="RTSP URL for target camera")
    parser.add_argument("--output_dir", type=str, default="data/stereo_pairs")
    args = parser.parse_args()

    zone_dir = os.path.join(args.output_dir, args.zone)
    os.makedirs(zone_dir, exist_ok=True)

    print(f"Opening streams...")
    master_stream = StreamReader(args.rtsp0, f"cam{args.master_id}").start()
    target_stream = StreamReader(args.rtsp1, f"cam{args.target_id}").start()

    # Wait for first frames.
    for _ in range(50):
        r0, f0 = master_stream.read()
        r1, f1 = target_stream.read()
        if r0 and r1:
            break
        time.sleep(0.1)
    else:
        print("[ERROR] Could not get frames from one or both streams.")
        master_stream.release()
        target_stream.release()
        return

    res0 = master_stream.resolution()
    res1 = target_stream.resolution()
    print(f"[OK] cam{args.master_id}: {res0[0]}x{res0[1]}  |  cam{args.target_id}: {res1[0]}x{res1[1]}")
    print(f"     Saving pairs to: {zone_dir}/pair_NNN/")
    print(f"     SPACE=save (board in BOTH cameras)  F=force-save  Q=quit\n")

    saved = 0

    while True:
        r0, f0 = master_stream.read()
        r1, f1 = target_stream.read()
        if not r0 or not r1 or f0 is None or f1 is None:
            time.sleep(0.01)
            continue

        found0, corners0 = detect_board(f0)
        found1, corners1 = detect_board(f1)
        both_found = found0 and found1

        d0 = annotate(f0, found0, corners0, f"cam{args.master_id} (master)", saved)
        d1 = annotate(f1, found1, corners1, f"cam{args.target_id} (target)", saved)

        # Stack side-by-side (resize target to match master height if needed).
        if d0.shape[0] != d1.shape[0]:
            scale = d0.shape[0] / d1.shape[0]
            d1 = cv2.resize(d1, (int(d1.shape[1] * scale), d0.shape[0]))
        combined = np.hstack([d0, d1])

        if both_found:
            cv2.putText(combined, "BOTH DETECTED — press SPACE to save",
                        (combined.shape[1] // 2 - 200, combined.shape[0] - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 220, 80), 2)

        # Scale combined down to fit on screen (max 1400px wide).
        max_w = 1400
        if combined.shape[1] > max_w:
            scale = max_w / combined.shape[1]
            combined = cv2.resize(combined, (max_w, int(combined.shape[0] * scale)))

        win = f"Extrinsic Capture — {args.zone}"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        cv2.imshow(win, combined)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord(' '):
            if both_found:
                pair_dir = os.path.join(zone_dir, f"pair_{saved + 1:03d}")
                os.makedirs(pair_dir, exist_ok=True)
                cv2.imwrite(os.path.join(pair_dir, f"cam_{args.master_id}.jpg"), f0)
                cv2.imwrite(os.path.join(pair_dir, f"cam_{args.target_id}.jpg"), f1)
                saved += 1
                print(f"  Saved pair {saved:03d}: {pair_dir}")
            else:
                missing = []
                if not found0: missing.append(f"cam{args.master_id}")
                if not found1: missing.append(f"cam{args.target_id}")
                print(f"  [skip] Board not detected in: {', '.join(missing)}")
        elif key == ord('f'):
            pair_dir = os.path.join(zone_dir, f"pair_{saved + 1:03d}")
            os.makedirs(pair_dir, exist_ok=True)
            cv2.imwrite(os.path.join(pair_dir, f"cam_{args.master_id}.jpg"), f0)
            cv2.imwrite(os.path.join(pair_dir, f"cam_{args.target_id}.jpg"), f1)
            saved += 1
            print(f"  Force-saved pair {saved:03d}")

    master_stream.release()
    target_stream.release()
    cv2.destroyAllWindows()
    print(f"\nDone. {saved} pairs saved.")
    if saved >= 10:
        print(f"Next: python calibrate_extrinsic.py --master_id {args.master_id} "
              f"--target_id {args.target_id} --zone {args.zone}")
    else:
        print(f"[warn] {saved} pairs is fewer than recommended (15+). More pairs = better accuracy.")


if __name__ == "__main__":
    main()
