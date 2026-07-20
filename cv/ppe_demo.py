"""
RigVision-3D — PPE Detection demo (standalone webcam).

Thin wrapper around cv/PPE/ppe_monitor.py: opens a webcam, feeds each frame to a
PPEMonitor (EfficientNet-B0 classifier backend) which handles person gating, face-crop
association, rolling-average smoothing, the 3-second debounce, proof frames, and the
Redis write. The same engine runs inside cv/pipeline.py.

All tunables come from .env (PPE_*). Run:  python cv/ppe_demo.py
"""

from __future__ import annotations

import os
import sys
import time

import cv2
import redis
import torch
from dotenv import load_dotenv

load_dotenv(override=True)

# Allow import from either cv/ or repo root
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cv.PPE.ppe_monitor import (  # noqa: E402
    PPEMonitor, CAP_CONFIRM_THRESHOLD, GLASSES_CONFIRM_THRESHOLD,
    DETECT_SECONDS, SCORE_WINDOW, PERSON_CONFIDENCE,
)

PERSON_MODEL   = os.getenv("YOLO_MODEL", "yolov8l.pt")
REDIS_HOST     = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None


def detect_persons(person_model, frame):
    """COCO person boxes (class 0) above PERSON_CONFIDENCE, as (x1,y1,x2,y2)."""
    res = person_model.predict(source=frame, conf=PERSON_CONFIDENCE, classes=[0], verbose=False)[0]
    return [tuple(b.xyxy[0].tolist()) for b in res.boxes]


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="RigVision PPE standalone demo")
    parser.add_argument("--source", default=None,
                        help="Camera index, RTSP URL, or video file path. "
                             "Defaults to PPE_CAMERA_INDEX env var (or 0).")
    args = parser.parse_args()

    # Resolve source: explicit arg > env var > 0
    if args.source is None:
        raw = os.getenv("PPE_CAMERA_INDEX", "0")
        try:
            source = int(raw)
        except ValueError:
            source = raw
    else:
        try:
            source = int(args.source)
        except ValueError:
            source = args.source

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[ppe] source={source}  device={device}  person_model={PERSON_MODEL}")
    print(f"[ppe] cap_thr={CAP_CONFIRM_THRESHOLD}  gl_thr={GLASSES_CONFIRM_THRESHOLD}  "
          f"window={SCORE_WINDOW}f  debounce={DETECT_SECONDS}s  person_conf={PERSON_CONFIDENCE}")

    from ultralytics import YOLO
    monitor = PPEMonitor(device=device)
    person_model = YOLO(PERSON_MODEL)
    person_model.to(device)

    r = None
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        r.ping()
        print("[ppe] Redis connected")
    except Exception as e:
        print(f"[ppe] Redis unavailable ({e}) — running without Redis")
        r = None

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"[ppe] could not open source: {source}")
    print("[ppe] running — press 'q' in the window to quit.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[ppe] frame grab failed")
                break

            person_boxes = detect_persons(person_model, frame)
            monitor.process(frame, r, person_boxes, now=time.time())

            hat    = monitor.states["head_protection"].confirmed
            glasses = monitor.states["eye_protection"].confirmed

            STATUS_COLOR = {
                "detected":  (0, 200, 0),
                "missing":   (0, 0, 220),
                "unknown":   (160, 160, 160),
                "no_person": (100, 100, 100),
            }
            for (x1, y1, x2, y2) in person_boxes:
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (200, 200, 200), 1)

                hat_col = STATUS_COLOR.get(hat, (160, 160, 160))
                gl_col  = STATUS_COLOR.get(glasses, (160, 160, 160))
                hat_txt = f"Hat: {'YES' if hat == 'detected' else 'NO' if hat == 'missing' else hat}"
                gl_txt  = f"Glasses: {'YES' if glasses == 'detected' else 'NO' if glasses == 'missing' else glasses}"

                # Background pill for readability
                for i, (txt, col) in enumerate([(hat_txt, hat_col), (gl_txt, gl_col)]):
                    ty = y1 - 12 - i * 22
                    (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
                    cv2.rectangle(frame, (x1, ty - th - 3), (x1 + tw + 4, ty + 3), (20, 20, 20), -1)
                    cv2.putText(frame, txt, (x1 + 2, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 1, cv2.LINE_AA)

            cv2.imshow("RigVision PPE Demo", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("[ppe] stopped.")


if __name__ == "__main__":
    main()
