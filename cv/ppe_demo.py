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
    PPEMonitor, CAP_THRESHOLD, GLASSES_THRESHOLD, DETECT_SECONDS, SCORE_WINDOW,
    PERSON_CONFIDENCE,
)

# Back-compat aliases used by the print below
MODEL_NAME     = "EfficientNet-B0 (cap + glasses classifiers)"
INFERENCE_IMGSZ = 224
PPE_CONFIDENCE  = CAP_THRESHOLD

CAMERA_INDEX   = int(os.getenv("PPE_CAMERA_INDEX", "0"))
CAMERA_INDEX   = int(os.getenv("PPE_CAMERA_INDEX", "0"))
PERSON_MODEL   = os.getenv("YOLO_MODEL", "yolov8l.pt")
REDIS_HOST     = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None


def detect_persons(person_model, frame):
    """COCO person boxes (class 0) above PERSON_CONFIDENCE, as (x1,y1,x2,y2)."""
    res = person_model.predict(source=frame, conf=PERSON_CONFIDENCE, classes=[0], verbose=False)[0]
    return [tuple(b.xyxy[0].tolist()) for b in res.boxes]


def main() -> None:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[ppe] device={device}  backend={MODEL_NAME}  person_model={PERSON_MODEL}")
    print(f"[ppe] cap_thr={PPE_CONFIDENCE}  gl_thr={GLASSES_THRESHOLD}  "
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

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        raise SystemExit(f"[ppe] could not open camera index {CAMERA_INDEX}")
    print("[ppe] running — press 'q' in the window to quit.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[ppe] frame grab failed")
                break

            person_boxes = detect_persons(person_model, frame)
            monitor.process(frame, r, person_boxes, now=time.time())
            monitor.annotate(frame)
            cv2.imshow("RigVision PPE Demo", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("[ppe] stopped.")


if __name__ == "__main__":
    main()
